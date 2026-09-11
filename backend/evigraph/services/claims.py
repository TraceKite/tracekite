"""Contract claims — the normative registry (design §4, impl §4).

A claim is an extraction-time statement: "this repo provides/consumes key K of
kind KIND". Claims persist as :GraphNode:ContractClaim nodes with EVIDENCED_BY
edges to the claiming code/config node; the linker joins them at rendezvous
nodes. Adding a kind = one registry row + an emitting parser + a consuming
resolver; `__post_init__` and `test_claim_admission.py` enforce all three.
"""

import hashlib
import re
from dataclasses import dataclass, field

from evigraph.models.graph_models import GraphNode
from evigraph.utils.evidence import evidence_path as _evidence_path

PROVIDES = "provides"
CONSUMES = "consumes"

HINT_SOURCES = ("discovery", "host", "config", "gateway_route", "path_segment",
                "catalog", "observability", "none")

GENERIC_NAME_DENYLIST = frozenset({
    "api", "app", "web", "worker", "backend", "frontend", "db", "redis",
    "gateway", "server",
})

ACTIVE_KINDS = {
    "svcname": "R0",
    "image": "R0",
    "route": "R4",
    "http": "R7",
    "webhook": "R13",  # a registered callback: deliveries will arrive here
    "cfgdef": "R9",     # a config/env key defined somewhere (k8s, compose, helm)
    "cfgread": "R9",    # a config/env key read by code
    "declared": "R2",   # declared deployment binding (GitOps source, selector)
    "policy": "R2",     # mesh/network policy: who may talk to whom
    "grpcop": "R5",     # a declared protobuf rpc: package.Service/Rpc
    "grpcstub": "R5",   # a generated server base or client stub site
    "graphqlop": "R8",  # a GraphQL root operation: Type.field
    "topic": "R6",      # a message topic/queue: kafka:orders, sqs:orders-queue
    "lib": "R3",        # a package coordinate as a version-free purl
    "dataset": "R10",   # a named dataset: index:owners, s3:bucket, wh:cat.sch.tbl
    "db": "R10",        # a relational/NoSQL table or collection
    "mcpop": "R11",     # an MCP tool/resource: mcp:server/tool
    "a2aop": "R11",     # an A2A agent skill: a2a:agent/skill
    "owner": "R12",     # an owning team: team:payments
}
RESERVED_KINDS = frozenset({"flag"})

_UNRESOLVABLE = re.compile(r"\$\{[^}]*\}|\bprocess\.env\.|\bos\.environ")

# Provenances whose claims are visible but never joined: a fixture URL is not a
# dependency, and a vendored library's endpoints belong to someone else.
EXCLUDED_PROVENANCE = frozenset({"test", "vendored", "spec"})


@dataclass
class ContractClaim:
    repo_id: str
    kind: str
    direction: str
    key: str
    service_hint: str | None = None
    hint_source: str = "none"
    evidence: list[str] = field(default_factory=list)
    env_scope: str | None = None
    attrs: dict = field(default_factory=dict)
    # Which object made this statement, e.g. "Service/orders" vs
    # "Deployment/orders-deploy". Two objects in one file can legitimately make
    # the same (kind, direction, key) claim — a Deployment labelled `orders` and
    # the Service named `orders` both say "this namespace provides orders" — and
    # without a discriminator the second one collides with the first and is
    # silently dropped, taking its selector and ports with it.
    subject: str = ""
    # Where the statement came from: "" (authored production code), "test",
    # "vendored" or "generated". Only the first two withhold matching.
    provenance: str = ""

    def __post_init__(self):
        if self.kind not in ACTIVE_KINDS and self.kind not in RESERVED_KINDS:
            raise ValueError(f"Unknown claim kind {self.kind!r}")
        if self.direction not in (PROVIDES, CONSUMES):
            raise ValueError(f"Bad claim direction {self.direction!r}")
        if self.hint_source not in HINT_SOURCES:
            raise ValueError(f"Bad hint_source {self.hint_source!r}")

    @property
    def id(self) -> str:
        """Stable, line-free identity (Invariant 3).

        The evidence *path* participates but never the line, so edits above a
        claim do not churn its id. ``subject`` distinguishes two objects in the
        same file making the same statement.
        """
        evidence_path = _evidence_path(self.evidence[0]) if self.evidence else ""
        digest = hashlib.sha256(
            f"{self.kind}:{self.direction}:{self.key}:{evidence_path}"
            f":{self.subject}".encode()
        ).hexdigest()[:16]
        return f"{self.repo_id}:ContractClaim:{digest}"

    @property
    def matchable(self) -> bool:
        """Whether the linker may join on this claim.

        Unmatchable claims are still stored, so a reviewer can see that the
        signal exists and why it was not used. Three reasons to withhold one:
        an empty or env-templated key, or a provenance
        (``test``/``vendored``) that makes the statement untrue of this system.
        """
        if self.provenance in EXCLUDED_PROVENANCE:
            return False
        return bool(self.key) and not _UNRESOLVABLE.search(self.key)


def svcname_key(scope: str, name: str) -> str:
    return f"{scope.lower()}:{name.lower()}"

def is_generic_name(name: str) -> bool:
    return name.lower() in GENERIC_NAME_DENYLIST


# Values that are still a template at ingest time: the chart/CI substitution
# never ran, so the text is a placeholder, not a name. Observed in the wild as
# real Service nodes on the map -- `{{ .values.otel.servicename | quote }}`
# rendered as a service alongside genuine ones, which is worse than a missing
# node because it looks like a finding.
_TEMPLATE_MARKERS = ("{{", "}}", "${", "%{", "<<", "__")


def is_unrendered_template(value: str) -> bool:
    """True when a claimed name is an unsubstituted template expression.

    Deliberately conservative: a name merely CONTAINING a brace or dollar is
    not enough (`api-$pecial` is a legal, if odd, name). The value must open a
    recognised interpolation, or be wholly wrapped in placeholder punctuation.
    """
    text = (value or "").strip()
    if not text:
        return False
    if any(marker in text for marker in ("{{", "}}", "${", "%{")):
        return True
    if text.startswith("<") and text.endswith(">"):
        return True
    if text.startswith("__") and text.endswith("__"):
        return True
    # A bare `$VAR` reference, but not a name that merely contains a dollar.
    return text.startswith("$") and text[1:].replace("_", "").isalnum()

def route_key(path_prefix: str, target: str) -> str:
    return f"{path_prefix}\u2192svcname:{target.lower()}"

def http_provides_key(method: str, path_template: str) -> str:
    return f"{method.upper()}:{path_template}"

def http_consumes_key(method: str, url_or_template: str) -> str:
    return f"httpcall:{method.upper()}:{url_or_template}"


def grpc_operation_key(package: str, service: str, rpc: str) -> str:
    """`package.Service/Rpc` — the wire path gRPC itself uses.

    Globally unique by construction, which is why R5 needs no service hint.
    """
    full = f"{package}.{service}" if package else service
    return f"{full}/{rpc}"


def graphql_operation_key(parent_type: str, field_name: str) -> str:
    """`Query.owner` — the key a schema and a client operation share.

    Unlike a protobuf key this carries no package, so two teams can define the
    same one; R8 treats that as ambiguous unless federation says who owns it.
    """
    return f"{parent_type}.{field_name}"


def config_key(scope: str, key: str) -> str:
    """Rendezvous key for a config/env variable (design §2.3 ConfigKey).

    Scope-qualified so a `PORT` in one namespace never joins a `PORT` in
    another. Env-var names are case-sensitive on every platform we target, so
    unlike service names these are NOT lowercased.
    """
    return f"{scope.lower()}:{key}"


def topic_key(system: str, name: str) -> str:
    """`kafka:order-events` — Kafka topic names are case-sensitive, so unlike
    service names the name part is NOT lowercased. `system` distinguishes an
    SQS queue named `orders` from a Kafka topic named `orders`; they are
    different rendezvous even under the same spelling."""
    return f"{system.lower()}:{name}"


_PURL_ECOSYSTEM_ALIASES = {
    "gomod": "golang", "go": "golang", "python": "pypi", "pip": "pypi",
    "js": "npm", "node": "npm", "gradle": "maven", "sbt": "maven",
    "rubygems": "gem", "crates": "cargo", "rust": "cargo",
}
_CASE_INSENSITIVE_ECOSYSTEMS = frozenset({"pypi", "nuget", "gem", "golang"})


def lib_key(ecosystem: str, name: str, namespace: str = "") -> str:
    """Version-free purl: `pkg:maven/org.example/lib`, `pkg:npm/@scope/name`.

    The version deliberately does not participate — the rendezvous is "the
    library", and per-consumer versions live on the DEPENDS_ON edges so version
    skew is a query, not a different node. pypi/nuget/gem/golang names are
    case-insensitive (and pypi treats `_` as `-`), so they are normalized;
    maven/npm/cargo names are case-sensitive and kept as written.
    """
    eco = _PURL_ECOSYSTEM_ALIASES.get(ecosystem.lower(), ecosystem.lower())
    if eco in _CASE_INSENSITIVE_ECOSYSTEMS:
        name, namespace = name.lower(), namespace.lower()
    if eco == "pypi":
        name = name.replace("_", "-")
    return f"pkg:{eco}/{namespace}/{name}" if namespace else f"pkg:{eco}/{name}"


def is_internal_lib(key: str, namespaces: dict) -> bool:
    """Whether a version-free purl falls inside the internal boundary.

    `namespaces` is the `ecosystems:` mapping from internal_namespaces.yml.
    Publish-side identity is checked elsewhere and beats this test.
    """
    if not key.startswith("pkg:"):
        return False
    body = key[4:]
    eco, _, rest = body.partition("/")
    spec = (namespaces or {}).get(eco) or {}
    if eco == "maven":
        namespace = rest.partition("/")[0]
        return any(namespace == n or namespace.startswith(f"{n}.")
                   for n in spec.get("namespaces") or [])
    if eco == "npm":
        return any(rest.startswith(f"{scope.lstrip('@')}/")
                   or rest.startswith(f"@{scope.lstrip('@')}/")
                   for scope in spec.get("scopes") or [])
    if eco == "golang":
        return any(rest.startswith(prefix.rstrip("/") + "/") or rest == prefix.rstrip("/")
                   for prefix in spec.get("module_prefixes") or [])
    prefixes = spec.get("prefixes") or []
    name = rest.rpartition("/")[2]
    return any(name.lower().startswith(prefix.lower()) for prefix in prefixes)


def dataset_key(kind: str, name: str, scope: str = "") -> str:
    """`index:owners`, `table:petclinic:owners`, `s3:media-bucket`,
    `wh:main.sales.orders`. `scope` carries connection identity (database
    name, catalog) when known; a bare table name without scope is joinable
    only under R10's single-declarer rule, never by spelling alone."""
    body = f"{scope}:{name}" if scope else name
    return f"{kind.lower()}:{body}"


def mcp_op_key(server: str, tool: str) -> str:
    """`mcp:github/create_issue` — the server name is the join key between a
    client's mcp.json entry and the repo implementing that server."""
    return f"mcp:{server}/{tool}"


def a2a_op_key(agent: str, skill: str) -> str:
    return f"a2a:{agent}/{skill}"


def team_key(name: str) -> str:
    return f"team:{name.lower()}"


def image_ref_key(image: str) -> str:
    """Registry-qualified image name without tag or digest."""
    ref, _, tail = image.partition("@")
    head, _, maybe_tag = ref.rpartition(":")
    if head and "/" not in maybe_tag:
        ref = head
    return ref.lower()


def claim_to_node(claim: ContractClaim) -> GraphNode:
    extra: dict = {
        "kind": claim.kind,
        "direction": claim.direction,
        "key": claim.key,
        "hint_source": claim.hint_source,
        "matchable": claim.matchable,
        "provenance": claim.provenance,
        "evidence": list(claim.evidence[:5]),
    }
    if claim.service_hint:
        extra["service_hint"] = claim.service_hint
    if claim.env_scope:
        extra["env_scope"] = claim.env_scope
    return GraphNode(
        id=claim.id,
        repo_id=claim.repo_id,
        type="ContractClaim",
        name=claim.key,
        label=f"{claim.kind} {claim.direction}: {claim.key}",
        path=_evidence_path(claim.evidence[0]) if claim.evidence else None,
        extra_props=extra,
        metadata=dict(claim.attrs),
    )
