"""The value objects the resolvers pass around.

Split out of `base.py`, which had accumulated the vocabulary and the machinery
in one file. These are data with invariants and no behaviour beyond them: a
rendezvous node about to be minted, a route rule a gateway declared, an
environment value resolved through a ConfigMap.

They are re-exported from `base` because every resolver imports them from
there, and moving fourteen import lines to make a file shorter would bury the
change that made it necessary.
"""

from dataclasses import dataclass, field

# Annotated on ResolverOutput.edges below. Imported even though only an
# annotation needs it: Python 3.12 evaluates dataclass annotations eagerly,
# so a missing name here is an import-time NameError on the deployment
# runtime while staying invisible on a 3.14 dev box, where PEP 649 defers
# evaluation. The whole test suite passes and the container will not boot.
from evigraph.models.graph_models import GraphEdge


@dataclass
class RendezvousSpec:
    label: str
    node_id: str
    props: dict


@dataclass
class ServiceSpec:
    service_id: str
    name: str
    is_gateway: bool = False
    repo_ids: list[str] = field(default_factory=list)


@dataclass
class RouteRule:
    prefix: str
    strip_prefix: int
    rewrite_pattern: str
    rewrite_replacement: str
    target_name: str
    evidence: list[str]
    # The repo whose config declared this route. Route tables are keyed by
    # gateway NAME, so two repos defining the same gateway share one table and
    # a consumer can be matched by a route its own repo never declared. That is
    # legitimate cross-repo resolution, but the evidence path alone would then
    # be resolved against the wrong repo and dead-link.
    repo_id: str = ""


@dataclass
class PendingCall:
    """A service-to-service call found before Service nodes exist."""
    source_name: str
    target_name: str
    resolver_id: str
    confidence: float
    evidence: list[str]
    source_repo: str
    via: str
    env_scope: str = ""
    # Cron expression when the caller is time-triggered. Empty means
    # "not scheduled", which is different from unknown and stays empty.
    schedule: str = ""
    # CALLS_SERVICE unless a resolver says otherwise: mesh policy edges
    # share the queue but must never masquerade as call edges.
    edge_type: str = "CALLS_SERVICE"


@dataclass
class PendingGitops:
    """A declared repo -> service binding from ArgoCD/Flux."""
    service_name: str
    source_repo_url: str
    claim_id: str
    claim_repo: str
    evidence: list[str]


@dataclass
class EnvValue:
    """A resolved environment-variable value, keyed by (scope, name)."""
    name: str
    scope: str
    value_class: str
    value_host: str = ""
    value_port: int = 0
    value_scheme: str = ""
    # Keyed digest of the raw value (redaction.hmac16). Lets R6 match a config
    # value against a code literal without the value itself ever being stored.
    value_hmac: str = ""
    origin: str = ""          # k8s_env | k8s_configmap | helm_values | compose
    evidence: list[str] = field(default_factory=list)
    repo_id: str = ""
    env_scope: str = ""
    # The workload this variable is injected into. Code that reads the variable
    # ships in that workload's image, which attributes the read far more
    # reliably than guessing from the reading file's directory.
    consumer_service: str = ""


@dataclass(frozen=True)
class NormalizedCall:
    """A consumer call site whose rendezvous key is final (architecture §4, I9).

    Naming the callee and rewriting the path are the two operations that CHANGE
    a claim's rendezvous key: a gateway strips `/api/vet` before forwarding, an
    alias renames the target, config indirection supplies a host the source
    never mentions. They must therefore finish before claims are partitioned by
    that key — a claim whose key changes mid-join belongs to a shard it was
    never routed to, and its edge is lost silently rather than loudly.

    Produced by the NORMALIZE phase, consumed by the joining resolvers. A call
    the phase could not qualify yields no record at all; the decline is already
    counted, so the resolver simply finds nothing and moves on.
    """
    service: str
    method: str
    template: str
    hint_source: str
    via_gateway: bool
    gateway_resolved: bool
    route_evidence: tuple[str, ...] = ()
    route_repo: str = ""
    # Route-table applications between the caller and the final service.
    # 0 = direct; 1 = one gateway (the tier's own meaning); >1 = a chain,
    # which R7 prices by compounding the tier.
    gateway_hops: int = 0


@dataclass
class ResolverOutput:
    rendezvous: list[RendezvousSpec] = field(default_factory=list)
    services: list[ServiceSpec] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)

    def extend(self, other: "ResolverOutput") -> None:
        self.rendezvous.extend(other.rendezvous)
        self.services.extend(other.services)
        self.edges.extend(other.edges)
