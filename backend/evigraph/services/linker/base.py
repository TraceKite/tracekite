"""Linker core: claim records, resolver context, fusion (design §6.1).

Resolvers are pure functions over the ClaimIndex; every match stamps
RESOLVED_TO. Confidence values come from config/confidence.yml.
"""

import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field

import yaml

from evigraph.engine_config import get_config
from evigraph.utils.evidence import evidence_path
from evigraph.models.graph_models import GraphEdge
# Re-exported: the value objects moved to `values.py`, but every resolver
# imports them from here, and a rename across fourteen files would bury
# the change that needed them moved.
from evigraph.services.linker.values import (                          # noqa: F401
    EnvValue, NormalizedCall, PendingCall, PendingGitops, RendezvousSpec,
    ResolverOutput, RouteRule, ServiceSpec,
)
from evigraph.telemetry import RunTimings

logger = logging.getLogger(__name__)

_PARAM = re.compile(r"\{[^}]*\}")
_DEFAULT_CONFIDENCE = 0.6
# Matches the `fanout_cap` in confidence.yml; used when the file omits it.
_DEFAULT_FANOUT_CAP = 32

# Single operator-facing control plane (design §12): confidence table, aliases,
# roster, promotions all live in one directory. KG_CONFIG_DIR overrides it;
# the default is the workspace-root `config/` beside `backend/`.
_DEFAULT_CONFIG_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "config"))


def config_dir() -> str:
    return os.path.abspath(get_config().config_dir or _DEFAULT_CONFIG_DIR)


# Signals that observe the same underlying fact correlate and must not
# noisy-OR each other; distinct groups are treated as independent evidence.
CORRELATION_GROUPS = {
    "resolver.compose@1": "topology",
    "resolver.k8s@1": "topology",
    "resolver.alias@1": "alias",
    "resolver.gateway@1": "route",
    "resolver.http@1": "http",
    "resolver.grpc@1": "grpc",
    "resolver.graphql@1": "graphql",
    "rollup.calls@1": "http",
    "rollup.deps@1": "rollup",
    # Env indirection reads the same manifests as the topology resolvers, so it
    # corroborates rather than independently confirms them.
    "resolver.env@1": "topology",
    "resolver.topic@1": "topic",
    "resolver.library@1": "package",
    "resolver.owner@1": "owner",
    "resolver.dataset@1": "data",
    "resolver.agent@1": "agent",
}
TOPOLOGY_RESOLVERS = {"resolver.compose@1", "resolver.k8s@1"}


@dataclass
class ClaimRecord:
    id: str
    repo_id: str
    kind: str
    direction: str
    key: str
    service_hint: str | None
    hint_source: str
    matchable: bool
    evidence: list[str]
    attrs: dict
    evidence_node_id: str | None
    evidence_node_type: str

    @property
    def primary_path(self) -> str:
        if not self.evidence:
            return ""
        return evidence_path(self.evidence[0])


class ClaimIndex:
    def __init__(self, claims: list[ClaimRecord]):
        self.claims = claims
        self._by_kind: dict[str, list[ClaimRecord]] = defaultdict(list)
        self._by_kind_key: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
        for claim in claims:
            self._by_kind[claim.kind].append(claim)
            self._by_kind_key[(claim.kind, claim.key)].append(claim)

    def kind(self, kind: str) -> list[ClaimRecord]:
        return self._by_kind.get(kind, [])

    def provides(self, kind: str) -> list[ClaimRecord]:
        return [c for c in self.kind(kind) if c.direction == "provides" and c.matchable]

    def consumes(self, kind: str) -> list[ClaimRecord]:
        return [c for c in self.kind(kind) if c.direction == "consumes" and c.matchable]

    def for_key(self, kind: str, key: str) -> list[ClaimRecord]:
        return self._by_kind_key.get((kind, key), [])

    @property
    def repo_ids(self) -> set[str]:
        return {c.repo_id for c in self.claims}


class LinkContext:
    def __init__(self, link_run_id: str, confidence: dict, aliases: dict):
        self.link_run_id = link_run_id
        self.confidence = confidence
        # Aliases are indexed under both their bare and scope-qualified forms:
        # the control-plane file documents `discovery:PAYMENT-SERVICE`, while
        # resolvers canonicalize the bare name they parsed out of a claim key.
        self._canon: dict[str, str] = {}
        for canonical, names in (aliases or {}).items():
            target = str(canonical).lower()
            self._canon[target] = target
            for name in names or []:
                alias = str(name).lower()
                self._canon[alias] = target
                bare = alias.rpartition(":")[2]
                # A qualified alias also matches its bare name, but never
                # clobbers a canonical that already owns that bare name.
                if bare and bare != alias:
                    self._canon.setdefault(bare, target)
        self.servicename_id: dict[tuple[str, str], str] = {}
        self.service_by_scope_name: dict[tuple[str, str], str] = {}
        self.service_by_name: dict[str, str] = {}
        self.service_name_of: dict[str, str] = {}
        self.service_repos: dict[str, set[str]] = defaultdict(set)
        self.module_services: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.rewrite_routes: dict[str, list[RouteRule]] = defaultdict(list)
        self.contract_repos: dict[str, set[str]] = defaultdict(set)
        self.counters: dict[str, int] = defaultdict(int)
        # Alongside the counters because they answer the neighbouring
        # question — counters say what the run found, timings say what it
        # cost — but kept a separate object because only one of the two is
        # data.
        self.timings = RunTimings()
        # Resolvers that run before Services exist queue their edges here and
        # the linker materializes them once R0 has minted service identities.
        self.pending_calls: list[PendingCall] = []
        self.pending_gitops: list[PendingGitops] = []
        self.env_values: dict[tuple[str, str], EnvValue] = {}
        # Output of the NORMALIZE phase, keyed by claim id. Populated once,
        # between the resolvers that contribute broadcast state and the ones
        # that join on it; read-only thereafter (invariant I9).
        self._normalized_calls: dict[str, NormalizedCall] | None = None
        # Repos present in this link run; GitOps URLs are only bound to
        # repos we actually ingested.
        self.known_repos: set[str] = set()

    @property
    def normalized_calls(self) -> dict[str, "NormalizedCall"]:
        """Frozen rendezvous keys, or a loud failure if NORMALIZE was skipped.

        A joining resolver that finds this empty would emit nothing and report
        success — a silent zero-edge run, which is the exact failure this phase
        exists to prevent. So the unset state is distinguished from the empty
        one and raises instead.
        """
        if self._normalized_calls is None:
            raise RuntimeError(
                "NORMALIZE has not run, so rendezvous keys are still "
                "provisional. Drive resolvers through "
                "linker.service.run_resolvers() rather than iterating "
                "RESOLVERS directly (architecture §4, invariant I9)."
            )
        return self._normalized_calls

    @normalized_calls.setter
    def normalized_calls(self, value: dict[str, "NormalizedCall"]) -> None:
        self._normalized_calls = value

    def canon(self, name: str | None) -> str:
        name = (name or "").lower()
        return self._canon.get(name, name)

    def conf(self, resolver: str, tier: str) -> float:
        return float(self.confidence.get(resolver, {})
                     .get(tier, _DEFAULT_CONFIDENCE))

    @property
    def fanout_cap(self) -> int:
        """Most contracts one call site may match before the match is declined.

        A call site that matches everything has matched nothing: past this many
        candidates a resolver counts `fanout_exceeded` and emits nothing, rather
        than a fan of edges no reviewer could check. Never emit a truncated
        slice — that reads as a resolved match while hiding the ambiguity.

        Read from the control-plane file so an operator can tune it, and lives
        here rather than in app settings so resolvers stay independent of the
        server's environment (architecture §2).
        """
        return int(self.confidence.get("fanout_cap", _DEFAULT_FANOUT_CAP))

    def register_module(self, repo_id: str, config_path: str, service_name: str,
                        rank: int = 0) -> None:
        """Bind the directory a service-name claim came from to that service.

        ``rank`` breaks ties when several signals claim the same directory: a
        deployment descriptor naming a build context (2) beats an in-code
        application name (1) beats a whole-repo fallback (0). Longest prefix is
        still tried first — that is what makes monorepos resolve per-module.
        """
        prefix = config_path.split("/src/")[0] if "/src/" in config_path \
            else os.path.dirname(config_path)
        self.register_module_prefix(repo_id, prefix, service_name, rank)

    def register_module_prefix(self, repo_id: str, prefix: str,
                               service_name: str, rank: int = 0) -> None:
        prefix = (prefix or "").strip("/")
        entry = (prefix, service_name, rank)
        if entry not in self.module_services[repo_id]:
            self.module_services[repo_id].append(entry)
        # Longest prefix first, then highest rank.
        self.module_services[repo_id].sort(key=lambda t: (-len(t[0]), -t[2]))

    def module_service_name(self, repo_id: str, path: str) -> str | None:
        """Service owning ``path``, or None when the evidence is ambiguous.

        Two different services claiming the same directory at the same rank is
        not a tie to break arbitrarily — an arbitrary pick silently mis-attributes
        every contract under that path, so we decline instead (precision first).
        """
        path = (path or "").strip("/")
        best: tuple[int, int] | None = None
        names: set[str] = set()
        for prefix, name, rank in self.module_services.get(repo_id, []):
            if prefix and not (path == prefix or path.startswith(prefix + "/")):
                continue
            key = (len(prefix), rank)
            if best is None or key > best:
                best, names = key, {name}
            elif key == best:
                names.add(name)
        if len(names) != 1:
            if len(names) > 1:
                self.count("scope.ambiguous")
            return None
        return names.pop()

    def scope_for(self, repo_id: str, path: str) -> str:
        """Service scope owning ``path``, falling back to the repo id.

        Every ``provides`` service-name claim registers a scope, so an
        HTTP contract is keyed by service name whether that name came from
        docker-compose, a k8s manifest, or spring.application.name. Without
        this, non-JVM providers key contracts on repo_id and no consumer hint
        can ever match them.
        """
        return self.module_service_name(repo_id, path) or repo_id

    def count(self, key: str, n: int = 1) -> None:
        self.counters[key] += n
        # The decline channel is also the hook's channel. Imported here
        # rather than at module scope because `hooks` is imported by the
        # engine, which imports this module.
        from evigraph.services.linker.hooks import on_decline

        on_decline(key, n, self)

    def register_alias(self, alias: str, canonical: str) -> None:
        """Map an additional spelling onto a canonical service name.

        Used for cluster-DNS forms and Service/workload name pairs. Operator
        overrides from service_aliases.yml always win, so an existing mapping
        is never replaced.
        """
        alias, canonical = (alias or "").lower(), (canonical or "").lower()
        if not alias or not canonical or alias == canonical:
            return
        self._canon.setdefault(alias, canonical)

    def record_service_call(self, source_name: str, target_name: str,
                            resolver_id: str, confidence: float,
                            evidence: list[str], source_repo: str, *,
                            via: str, env_scope: str = "",
                            schedule: str = "",
                            edge_type: str = "CALLS_SERVICE") -> None:
        self.pending_calls.append(PendingCall(
            source_name=source_name, target_name=target_name,
            resolver_id=resolver_id, confidence=confidence,
            evidence=list(evidence or []), source_repo=source_repo, via=via,
            env_scope=env_scope, schedule=schedule, edge_type=edge_type))

    def record_gitops_source(self, service_name: str, repo_url: str,
                             claim) -> None:
        self.pending_gitops.append(PendingGitops(
            service_name=service_name, source_repo_url=repo_url,
            claim_id=claim.id, claim_repo=claim.repo_id,
            evidence=list(claim.evidence or [])))

    def repo_id_for_url(self, url: str) -> str | None:
        """Map a git URL (e.g. an ArgoCD repoURL) to an ingested repo id.

        Returns None when the referenced repo is not in the graph — a GitOps
        manifest routinely points at repos outside the roster, and inventing a
        Repo node for one would fabricate a node with no contents.
        """
        from evigraph.utils.hashing import (
            extract_git_host, generate_repo_id, normalize_github_url,
        )
        try:
            normalized, owner, repo = normalize_github_url(url)
            repo_id = generate_repo_id(owner, repo, extract_git_host(normalized))
        except ValueError:
            return None
        return repo_id if repo_id in self.known_repos else None

    def record_env_value(self, value: EnvValue) -> None:
        """Later definitions do not silently overwrite earlier ones; the most
        specific scope wins so a base values.yml cannot clobber an overlay."""
        key = (value.scope, value.name)
        current = self.env_values.get(key)
        if current is None or (not current.env_scope and value.env_scope):
            self.env_values[key] = value


def positional(template: str) -> str:
    return _PARAM.sub("{}", template or "")


def linker_edge(ctx: LinkContext, resolver_id: str, edge_type: str,
                source_id: str, target_id: str, *, source_label: str,
                target_label: str, confidence: float, match_type: str,
                evidence: list[str], claim_key: str = "",
                source_repo: str = "", target_repo: str = "",
                origin: str = "matched", status: str = "active",
                extra: dict | None = None) -> GraphEdge:
    extra = dict(extra or {})
    extra.setdefault("min_confidence", confidence)
    extra.setdefault("max_confidence", confidence)
    edge = GraphEdge(
        source_id=source_id, target_id=target_id, repo_id="", type=edge_type,
        confidence=confidence, origin=origin, detected_by=resolver_id,
        match_type=match_type, evidence=(evidence or [])[:5],
        source_repo_id=source_repo, target_repo_id=target_repo,
        cross_repo=bool(source_repo and target_repo and source_repo != target_repo),
        created_by="linker", status=status, claim_key=claim_key,
        link_run_id=ctx.link_run_id, extra_props=extra,
    )
    edge.source_label = source_label
    edge.target_label = target_label
    return edge


# extra_props that fusion recomputes rather than inherits.
_FUSION_COMPUTED = {"via", "min_confidence", "max_confidence"}
# List-valued props whose members union across the group (bounded).
_FUSION_UNION_LISTS = {"via", "evidence_edge_ids"}
_EVIDENCE_EDGE_ID_CAP = 10


def fuse_edges(edges: list[GraphEdge], cap: float = 0.99) -> list[GraphEdge]:
    """Same logical edge from several resolvers: max within a correlation
    group, noisy-OR across groups, capped (design §6.2 Fusion).

    Every contributor's ``extra_props`` are merged into the survivor. Inheriting
    only the highest-confidence edge's props drops ``evidence_edge_ids`` from
    corroborated Layer-2 rollups, which breaks the zoom-down invariant
    (design §5.3) exactly on the edges most likely to be shown.
    """
    grouped: dict[tuple, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        grouped[(edge.source_id, edge.type, edge.target_id)].append(edge)

    fused: list[GraphEdge] = []
    for group in grouped.values():
        if len(group) == 1:
            fused.append(group[0])
            continue
        by_corr: dict[str, float] = defaultdict(float)
        for edge in group:
            corr = CORRELATION_GROUPS.get(edge.detected_by, edge.detected_by)
            by_corr[corr] = max(by_corr[corr], edge.confidence)
        product = 1.0
        for conf in by_corr.values():
            product *= (1.0 - conf)
        confidence = min(cap, 1.0 - product)

        base = max(group, key=lambda e: e.confidence)
        merged = _merge_extra_props(group)

        base.confidence = confidence
        base.detected_by = "+".join(sorted({e.detected_by for e in group}))
        evidence: list[str] = []
        for edge in group:
            evidence.extend(edge.evidence)
        base.evidence = list(dict.fromkeys(evidence))[:5]

        # Repo attribution survives if any contributor carried it.
        for edge in group:
            base.source_repo_id = base.source_repo_id or edge.source_repo_id
            base.target_repo_id = base.target_repo_id or edge.target_repo_id
        base.cross_repo = bool(base.source_repo_id and base.target_repo_id
                               and base.source_repo_id != base.target_repo_id)

        merged["min_confidence"] = min(
            e.extra_props.get("min_confidence", e.confidence) for e in group)
        merged["max_confidence"] = confidence
        base.extra_props = merged
        fused.append(base)
    return fused


def _merge_extra_props(group: list[GraphEdge]) -> dict:
    """Union list props, sum weights/counts, first-wins for everything else."""
    merged: dict = {}
    unions: dict[str, list] = defaultdict(list)
    for edge in group:
        for key, value in edge.extra_props.items():
            if key in _FUSION_UNION_LISTS and isinstance(value, list):
                unions[key].extend(value)
            elif key in ("weight", "count") and isinstance(value, (int, float)):
                merged[key] = merged.get(key, 0) + value
            elif key not in _FUSION_COMPUTED and key not in merged:
                merged[key] = value
    for key, values in unions.items():
        deduped = list(dict.fromkeys(values))
        merged[key] = (sorted(deduped) if key == "via"
                       else deduped[:_EVIDENCE_EDGE_ID_CAP])
    return merged


class ConfidenceTableMissing(RuntimeError):
    """Raised when the control-plane confidence table cannot be found."""


def load_confidence() -> dict:
    """Resolver confidence table; fails closed if the control plane is missing.

    Without it every tier falls back to 0.6 — which is exactly the floor, so
    every edge would publish as `active` at the lowest defensible confidence
    while looking like a calibrated result. A misconfigured path must break the
    link run, not quietly flatten the confidence model.
    """
    path = os.path.join(config_dir(), "confidence.yml")
    if not os.path.exists(path):
        raise ConfidenceTableMissing(
            f"No confidence.yml at {path}. Set KG_CONFIG_DIR to the control-plane "
            f"directory; refusing to link with uncalibrated confidences."
        )
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_promotions() -> list[dict]:
    """Operator decisions on reviewed matches (design D6).

    Each entry: {source, type, target, decision: promote|reject, note}.
    Replayed on every link run so a decision survives relinks — an edge the
    linker scores sub-floor stays `active` once an operator promoted it, and a
    rejected edge stays `rejected` even though the resolvers recreate it.
    """
    path = os.path.join(config_dir(), "promotions.yml")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return [p for p in (data.get("promotions") or [])
            if isinstance(p, dict) and p.get("source") and p.get("target")]



def load_internal_namespaces() -> dict:
    """Internal package-coordinate boundary (design §12).

    Missing file means "publish-side identity only": consumed libraries link
    only when an ingested repo publishes the coordinate. That is the safe
    default — it can under-link, never wrongly link."""
    path = os.path.join(config_dir(), "internal_namespaces.yml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("ecosystems") or {}


def load_aliases() -> dict:
    """Operator alias overrides from the control-plane file (design §12).

    Documented schema: ``services: {canonical: {aliases: [...], repo: ...}}``.
    Aliases may be bare (``payment-svc``) or scope-qualified
    (``discovery:PAYMENT-SERVICE``); both forms are accepted because the
    control-plane file documents the qualified form while resolvers canonicalize
    bare names. Returns ``{canonical_name: [claimed_aliases, ...]}``.
    """
    path = os.path.join(config_dir(), "service_aliases.yml")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    services = data.get("services") or {}
    return {canonical: list((spec or {}).get("aliases") or [])
            for canonical, spec in services.items()}
