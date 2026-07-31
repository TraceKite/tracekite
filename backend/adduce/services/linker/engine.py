"""The link engine: claims in, edges out. No server, no database, no I/O.

This is half of the public contract. `link()` takes claims someone else
obtained — from Neo4j, from a JSON artifact, from a test fixture — and returns
what the join produced. It never reads or writes storage, which is what lets a
host embed it without adopting any of Adduce's infrastructure.

`LinkerService` in `service.py` is the application's driver: it fetches claims
through the store port, calls `link()`, and writes the result back. There is
one implementation of the join and both surfaces use it — a second copy tuned
for the library would drift, and library users would silently get a different
graph from app users.

**Determinism.** `link()` is a pure function of its arguments with one
exception: `now` defaults to the wall clock because rollup edges carry a
timestamp. Pass `now` to make a run reproducible; B6 makes that the default.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from adduce.services.linker import hooks
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput,
    linker_edge, load_aliases, load_confidence,
)
from adduce.services.linker.edge_policy import finalize_edges
from adduce.services.linker.normalize import normalize_http_calls
from adduce.services.linker.partitions import hot_key_sizes
# Re-exported: the roster moved to `registry.py`, but `engine` is where every
# caller already looks for it, and renaming an import path across the tools
# and tests would be a bigger change than the one being made.
from adduce.services.linker.registry import (                     # noqa: F401
    BROADCAST_RESOLVERS, JOIN_RESOLVERS, RESOLVERS, SHIPPED_PRECEDENCE,
    clear_registered_resolvers, declared_order, register_resolver,
    registered_resolvers, resolver_order,
)
from adduce.services.linker.rollups import build_rollups
from adduce.telemetry import RunTimings, timed

logger = logging.getLogger(__name__)

# The pool width skew is judged against — scan_many's cap, and fixed so the
# counters are a property of the estate, not of whoever linked it.
_REFERENCE_WORKERS = 16

@dataclass
class LinkResult:
    """Everything one link run produced. Values only — nothing is persisted."""

    edges: list = field(default_factory=list)
    rendezvous: list = field(default_factory=list)
    services: list = field(default_factory=list)
    counters: dict = field(default_factory=dict)
    repo_ids: list[str] = field(default_factory=list)
    # What the run cost, per step. Reported, never persisted: a duration
    # differs between two runs over identical claims, and an artifact that
    # differs from itself breaks every gate built on determinism.
    timings: RunTimings = field(default_factory=RunTimings)


def run_resolvers(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    """Drive one link pass: BROADCAST, then NORMALIZE, then JOIN.

    The phase order is a property of the pipeline, not of each caller, so it
    lives here rather than being re-implemented by anything that needs a link
    run. Iterating RESOLVERS directly skips NORMALIZE and leaves rendezvous
    keys provisional — LinkContext raises rather than let that pass silently.
    """
    combined = broadcast_pass(index, ctx)
    combined.extend(join_pass(index, ctx))
    # Named in the counters so a graph built with host extensions is not
    # mistaken for one built by the shipped resolvers alone.
    for names in registered_resolvers().values():
        for name in names:
            ctx.count(f"registered.{name}")
    return combined


def _group(group, index: ClaimIndex, ctx: LinkContext,
           combined: ResolverOutput) -> None:
    for name, module in group:
        hooks.pre_resolve(name, index, ctx)
        with timed(ctx.timings, f"resolver.{name}"):
            output = module.resolve(index, ctx)
        output = hooks.post_resolve(name, output, ctx)
        combined.extend(output)
        # Yield is counted, not just logged: a resolver that quietly
        # stops matching drops recall without raising, and a zero here
        # is the only thing that says so. Counted even when zero — an
        # absent counter reads as "not measured", which is the implied
        # absence this codebase keeps refusing.
        ctx.count(f"yield.{name}.edges", len(output.edges))
        ctx.count(f"yield.{name}.rendezvous", len(output.rendezvous))
        logger.info(
            "Linker %s: %d edges, %d rendezvous in %.3fs", name,
            len(output.edges), len(output.rendezvous),
            ctx.timings.steps.get(f"resolver.{name}", 0.0),
            extra={"link_run_id": ctx.link_run_id, "resolver": name})


def broadcast_pass(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    """BROADCAST, then NORMALIZE: everything that is global by design.

    Exposed apart from `join_pass` for claim-level invalidation, which
    must always rerun this half — side tables and key freezing read the
    whole estate — while rerunning only touched partitions of the other.
    """
    combined = ResolverOutput()
    with timed(ctx.timings, "phase.broadcast"):
        _group(resolver_order("broadcast"), index, ctx, combined)
    # NORMALIZE: every rendezvous key becomes final here, while the whole
    # estate is still in one place. After this point a key may be read but
    # never rewritten, which is what makes the join partitionable (I9).
    with timed(ctx.timings, "phase.normalize"):
        ctx.normalized_calls = normalize_http_calls(index, ctx)
    logger.info("Linker normalize: %d call sites keyed",
                len(ctx.normalized_calls),
                extra={"link_run_id": ctx.link_run_id})
    return combined


def join_pass(index: ClaimIndex, ctx: LinkContext,
              only: set[str] | None = None) -> ResolverOutput:
    """The join resolvers, against frozen keys. Partitionable (I9, I10).

    `only` restricts the pass to the named RESOLVER_IDs — the incremental
    engine's contract. Resolver KINDS overlap (r13 and r14 both read http
    claims), so re-running every resolver over a rerun set's claims would
    re-emit edges whose priors were kept, and the graph would hold both.
    """
    combined = ResolverOutput()
    with timed(ctx.timings, "phase.join"):
        order = resolver_order("join")
        if only is not None:
            order = [(name, module) for name, module in order
                     if getattr(module, "RESOLVER_ID", name) in only]
        _group(order, index, ctx, combined)
    return combined


def materialize_pending(ctx: LinkContext) -> list:
    """Turn queued name-level findings into Service-level edges.

    R2 and R9 discover calls before Service identities exist (R2 runs first so
    its aliases inform clustering; R9 resolves through config that R0 must
    already have scoped). Both queue by *name*; here the names are looked up
    against the Services R0 actually minted, and anything that does not resolve
    is counted rather than invented.
    """
    edges = []
    for pending in ctx.pending_calls:
        source_id = ctx.service_by_name.get(pending.source_name)
        target_id = ctx.service_by_name.get(pending.target_name)
        if source_id is None or target_id is None:
            ctx.count("pending.calls_unminted")
            continue
        if source_id == target_id:
            ctx.count("pending.calls_self")
            continue
        extra = {"via": [pending.via]}
        if pending.env_scope:
            extra["env_scope"] = pending.env_scope
        if pending.schedule:
            extra["schedule"] = pending.schedule
        edges.append(linker_edge(
            ctx, pending.resolver_id, pending.edge_type, source_id, target_id,
            source_label="Service", target_label="Service",
            confidence=pending.confidence, match_type=pending.via,
            evidence=pending.evidence, source_repo=pending.source_repo,
            origin="matched", extra=extra,
        ))
        ctx.count("pending.calls_materialized")

    for pending in ctx.pending_gitops:
        service_id = ctx.service_by_name.get(pending.service_name)
        repo_id = ctx.repo_id_for_url(pending.source_repo_url)
        if service_id is None or repo_id is None:
            ctx.count("pending.gitops_unresolved")
            continue
        ctx.service_repos[service_id].add(repo_id)
        edges.append(linker_edge(
            ctx, "resolver.k8s@1", "BUILT_FROM", service_id, repo_id,
            source_label="Service", target_label="Repo",
            confidence=ctx.conf("r2", "built_from_gitops"),
            match_type="gitops", evidence=pending.evidence,
            target_repo=repo_id, origin="declared",
            extra={"via": ["gitops"]},
        ))
        ctx.count("pending.gitops_materialized")
    return edges


def dedupe_rendezvous(combined: ResolverOutput) -> list:
    merged: dict[tuple[str, str], dict] = {}
    order = []
    for spec in combined.rendezvous:
        key = (spec.label, spec.node_id)
        if key not in merged:
            merged[key] = spec.props
            order.append(spec)
        else:
            existing = set(merged[key].get("repo_ids", []))
            existing.update(spec.props.get("repo_ids", []))
            merged[key]["repo_ids"] = sorted(existing)
    return order


def annotate_cardinality(rendezvous: list, edges: list) -> None:
    """Fan-in and fan-out on every rendezvous node.

    A contract with forty consumers is not the risk of one with a single
    consumer, and until now the graph could not tell them apart: both were
    "an HttpContract with edges". Blast radius is the question this tool
    exists to answer, and it is a number.

    Counted from the edges of *this* run rather than kept as a running side
    table — O(contracts), computed once, and never claim-proportional (I8).

    Distinct counterparties, not edge count. Two resolvers corroborating the
    same consumer fuse into one edge but could arrive as two; counting edges
    would report a fan-in of two for one caller and overstate the blast
    radius, which is the direction that misleads.
    """
    inbound: dict[str, set[str]] = {}
    outbound: dict[str, set[str]] = {}
    for edge in edges:
        if edge.status != "active":
            # Candidates are excluded from default answers, so including them
            # here would inflate a number people act on.
            continue
        inbound.setdefault(edge.target_id, set()).add(edge.source_id)
        outbound.setdefault(edge.source_id, set()).add(edge.target_id)

    for spec in rendezvous:
        spec.props["fan_in"] = len(inbound.get(spec.node_id, ()))
        spec.props["fan_out"] = len(outbound.get(spec.node_id, ()))


def dedupe_services(combined: ResolverOutput) -> list:
    by_id: dict[str, object] = {}
    for spec in combined.services:
        current = by_id.get(spec.service_id)
        if current is None:
            by_id[spec.service_id] = spec
        else:
            current.is_gateway = current.is_gateway or spec.is_gateway
            current.repo_ids = sorted(set(current.repo_ids) | set(spec.repo_ids))
    return list(by_id.values())


def link(claims: list[ClaimRecord], *, run_id: str = "linkrun_local",
         confidence: dict | None = None, aliases: dict | None = None,
         promotions: list | None = None, now: str | None = None) -> LinkResult:
    """Join claims into edges. No database, no server, no network.

    `confidence`, `aliases` and `promotions` default to the operator control
    plane on disk (`config/*.yml`). Pass them explicitly to run against values
    a host supplies instead — that, and nothing else, is what the control plane
    is for.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    ctx = LinkContext(
        run_id,
        load_confidence() if confidence is None else confidence,
        load_aliases() if aliases is None else aliases,
    )
    with timed(ctx.timings, "phase.index"):
        index = ClaimIndex(claims)
    ctx.known_repos = set(index.repo_ids)
    ctx.count("claims_loaded", len(claims))
    # Skew detection, live on every run: REDUCE partitions by key, so
    # a hot key is the shard no worker count can shrink. Counted against a
    # fixed reference width rather than the machine's cores — a counter
    # that changed with the hardware would break determinism (I1).
    hot = hot_key_sizes(claims, _REFERENCE_WORKERS)
    ctx.count("skew.hot_keys", len(hot))
    ctx.count("skew.largest_hot_key_claims",
              max(hot.values()) if hot else 0)

    combined = run_resolvers(index, ctx)
    with timed(ctx.timings, "phase.materialize"):
        combined.edges.extend(materialize_pending(ctx))
        combined.edges.extend(build_rollups(ctx, combined.edges, now))

    edges = finalize_edges(ctx, combined, promotions)

    with timed(ctx.timings, "phase.cardinality"):
        rendezvous = dedupe_rendezvous(combined)
        annotate_cardinality(rendezvous, edges)

    logger.info("Link run %s: %d edges from %d claims in %.3fs", run_id,
                len(edges), len(claims), ctx.timings.total,
                extra={"link_run_id": run_id})
    return LinkResult(
        edges=edges,
        rendezvous=rendezvous,
        services=dedupe_services(combined),
        counters=dict(sorted(ctx.counters.items())),
        repo_ids=sorted(index.repo_ids),
        timings=ctx.timings,
    )
