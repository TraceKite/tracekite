"""Layer-2 rollups: CALLS_SERVICE from INVOKES, DEPENDS_ON_REPO from all
cross-repo signals (design §2.2). Rollup edges carry weight/via/min/max
confidence and evidence_edge_ids; they delete by link_run_id only."""

from collections import defaultdict

from evigraph.models.graph_models import GraphEdge
from evigraph.services.linker.base import LinkContext, linker_edge
from evigraph.utils.evidence import evidence_path

CALLS_ID = "rollup.calls@1"
DEPS_ID = "rollup.deps@1"


def build_rollups(ctx: LinkContext, edges: list[GraphEdge],
                  now: str) -> list[GraphEdge]:
    rollups: list[GraphEdge] = []
    calls = _calls_service(ctx, edges, now)
    rollups.extend(calls)
    # Derived CALLS_SERVICE edges are themselves cross-repo signals, so the
    # repo overlay is computed over resolver output *and* the calls rollup.
    rollups.extend(_depends_on_repo(ctx, edges + calls, now))
    return rollups


def _consumer_service(ctx: LinkContext, edge: GraphEdge) -> str | None:
    path = evidence_path(edge.evidence[0]) if edge.evidence else ""
    name = ctx.module_service_name(edge.source_repo_id, path)
    if name is None:
        return None
    return ctx.service_by_name.get(ctx.canon(name))


def _service_repos(ctx: LinkContext, service_id: str | None) -> set[str]:
    return ctx.service_repos.get(service_id, set()) if service_id else set()


def _sole_repo(repos: set[str]) -> str:
    """Repo attribution only when unambiguous — a Service built from two repos
    cannot attribute a rollup edge to either without guessing."""
    return next(iter(repos)) if len(repos) == 1 else ""


def _contract_service(ctx: LinkContext, contract_id: str) -> str | None:
    parts = contract_id.split(":", 4)
    if len(parts) < 5:
        return None
    return ctx.service_by_name.get(ctx.canon(parts[2]))


def _calls_service(ctx: LinkContext, edges: list[GraphEdge],
                   now: str) -> list[GraphEdge]:
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"weight": 0, "confs": [], "eids": [], "evidence": [], "via": set()})
    for edge in edges:
        if edge.type not in ("INVOKES", "UI_CALLS"):
            continue
        source = _consumer_service(ctx, edge)
        target = _contract_service(ctx, edge.target_id)
        if source is None or target is None:
            ctx.count("rollup.calls_unmapped")
            continue
        if source == target:
            ctx.count("rollup.calls_intra_skipped")
            continue
        group = groups[(source, target)]
        group["weight"] += 1
        group["confs"].append(edge.confidence)
        if len(group["eids"]) < 10:
            group["eids"].append(
                f"{edge.source_id}|{edge.type}|{edge.target_id}")
        group["evidence"].extend(edge.evidence[:1])
        via = edge.extra_props.get("via") or []
        if "gateway_rewrite" in via and len(edge.evidence) > 1:
            # R7 appends the route table's own file:line LAST, and it is the
            # half of the receipt that names the target — a gateway-relative
            # call site never does. Dropping it made the fused edge cite only
            # `$http.get("api/customer/...")`, which a reader cannot confirm
            # names customers-service.
            group["evidence"].append(edge.evidence[-1])
        group["via"].update(edge.extra_props.get("via", ["http"]))

    result = []
    for (source, target), group in sorted(groups.items()):
        # Layer-2 edges carry repo attribution too, so cross_repo and the
        # DEPENDS_ON_REPO rollup below can both see them.
        source_repo = _sole_repo(_service_repos(ctx, source))
        target_repo = _sole_repo(_service_repos(ctx, target))
        result.append(linker_edge(
            ctx, CALLS_ID, "CALLS_SERVICE", source, target,
            source_label="Service", target_label="Service",
            confidence=max(group["confs"]), match_type="rollup",
            evidence=group["evidence"][:5], origin="inferred",
            source_repo=source_repo, target_repo=target_repo,
            extra={"weight": group["weight"], "via": sorted(group["via"]),
                   "min_confidence": min(group["confs"]),
                   "max_confidence": max(group["confs"]),
                   "evidence_edge_ids": group["eids"],
                   "derived_by": CALLS_ID, "resolved_at": now},
        ))
        ctx.count("rollup.calls_service")
    return result


def _depends_on_repo(ctx: LinkContext, edges: list[GraphEdge],
                     now: str) -> list[GraphEdge]:
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "confs": [], "via": set(), "evidence": []})

    def add(source_repo: str, target_repo: str, via: str, confidence: float,
            evidence: list[str]) -> None:
        if not source_repo or not target_repo or source_repo == target_repo:
            return
        group = groups[(source_repo, target_repo)]
        group["count"] += 1
        group["confs"].append(confidence)
        group["via"].add(via)
        group["evidence"].extend(evidence[:1])

    for edge in edges:
        if edge.type in ("INVOKES", "UI_CALLS") and edge.cross_repo:
            add(edge.source_repo_id, edge.target_repo_id, "http",
                edge.confidence, edge.evidence)
        elif edge.type == "CALLS_SERVICE":
            via = "http" if edge.detected_by == CALLS_ID else "compose"
            if edge.cross_repo:
                add(edge.source_repo_id, edge.target_repo_id, via,
                    edge.confidence, edge.evidence)
            else:
                # Service ids resolve to repos even when the edge itself
                # carries no attribution (e.g. a multi-repo Service).
                for src_repo in sorted(_service_repos(ctx, edge.source_id)):
                    for dst_repo in sorted(_service_repos(ctx, edge.target_id)):
                        add(src_repo, dst_repo, via, edge.confidence,
                            edge.evidence)
        elif edge.type == "ROUTES_TO":
            for src_repo in sorted(_service_repos(ctx, edge.source_id)):
                for dst_repo in sorted(_service_repos(ctx, edge.target_id)):
                    add(src_repo, dst_repo, "route", edge.confidence, edge.evidence)

    result = []
    for (source, target), group in sorted(groups.items()):
        result.append(linker_edge(
            ctx, DEPS_ID, "DEPENDS_ON_REPO", source, target,
            source_label="Repo", target_label="Repo",
            confidence=max(group["confs"]), match_type="rollup",
            evidence=group["evidence"][:5], source_repo=source,
            target_repo=target, origin="inferred",
            extra={"count": group["count"], "via": sorted(group["via"]),
                   "min_confidence": min(group["confs"]),
                   "max_confidence": max(group["confs"]),
                   "derived_by": DEPS_ID, "resolved_at": now},
        ))
        ctx.count("rollup.depends_on_repo")
    return result
