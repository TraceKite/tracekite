"""Claim-level invalidation: only touched partitions re-resolve.

Built ahead of the estate that needs it, on the operator's explicit
decision (2026-07-29) — the full join measures 0.19s at 16.5K claims, so
today this saves milliseconds; what it buys is the machinery, proven
equivalent, for the estate where it saves minutes.

The unit of invalidation is a **resolver's slice of the claims**, decided
per changed claim. Rendezvous keys looked like the finer unit and are not:
a claim's `key` field is not every resolver's *join* key — R6 resolves an
env-indirected topic to a different final key at join time, and R11
matches consumers to providers through the server name across keys. The
first draft spliced by key and the equivalence tests caught both, one as a
silently missing edge and one as a silently kept stale edge. What IS sound
is the resolver slice: a join resolver's output depends only on its input
kinds' claims and the broadcast state (I10, statically enforced), so if
neither changed, all of its prior edges stand.

* **BROADCAST and NORMALIZE always rerun** — global by design. Whether
  their output moved is decided by digest, not by a hand-listed set of
  "broadcast kinds": that list would be the same silent-drift hole F3
  just closed.
* **A join resolver reruns iff a claim of its input kinds changed**; the
  others contribute their prior edges verbatim.
* **Rollups always recompute**, over kept and new edges together — a repo
  dependency derived from an untouched INVOKES is still this run's fact.

The contract is equivalence: `relink()` must produce exactly the edges and
rendezvous a full `link()` produces. The tests mutate one claim at a time
across every resolver family's estate and compare.
"""

import hashlib
import logging

from adduce.services.linker.base import ClaimIndex, LinkContext, ResolverOutput
from adduce.services.linker.edge_policy import finalize_edges
from adduce.services.linker.engine import (
    LinkResult, annotate_cardinality, broadcast_pass, dedupe_rendezvous,
    dedupe_services, join_pass, materialize_pending, registered_resolvers,
)
from adduce.services.linker.rollups import build_rollups

logger = logging.getLogger(__name__)

# Each join resolver's input kinds — the slice of the estate whose change
# dirties it. The equivalence tests are the drift guard: a resolver reading
# a kind missing here diverges the moment an estate mutates that kind.
RESOLVER_KINDS = {
    "resolver.grpc@1": frozenset({"grpcop", "grpcstub"}),
    "resolver.http@1": frozenset({"http"}),
    "resolver.graphql@1": frozenset({"graphqlop"}),
    "resolver.env@1": frozenset({"cfgread"}),
    "resolver.topic@1": frozenset({"topic"}),
    "resolver.dataset@1": frozenset({"dataset", "db"}),
    "resolver.agent@1": frozenset({"mcpop", "a2aop"}),
    "resolver.owner@1": frozenset({"owner"}),
    "resolver.webhook@1": frozenset({"webhook", "http"}),
    "resolver.operation@1": frozenset({"grpcop", "http", "topic"}),
}

# The service-call fusion clique. R2 (broadcast, always recomputed), R5, R9
# and the rollups all emit CALLS_SERVICE between the same Service nodes, and
# fusion merges them into one edge — so a prior fused edge is attributable
# to none of them alone. Keeping R5's or R9's share while R2's recomputes
# would either drop the kept side's evidence or, re-fused, duplicate it
# (fusion concatenates evidence; it is not idempotent). They rerun every
# time instead. The equivalence tests caught this as one evidence line
# quietly missing from a fused edge.
_ALWAYS_RERUN = frozenset({"resolver.grpc@1", "resolver.env@1"})


def changed_kinds(prior_claims: list, claims: list) -> set[str]:
    """The kinds of every claim that differs between the two estates.

    Identity is the claim id; change is full-record inequality, so an
    edited evidence line dirties its kind even though the key is unchanged.
    A claim whose kind itself changed dirties both.
    """
    before = {c.id: c for c in prior_claims}
    after = {c.id: c for c in claims}
    kinds: set[str] = set()
    for cid in before.keys() | after.keys():
        old, new = before.get(cid), after.get(cid)
        if old == new:
            continue
        kinds.update(c.kind for c in (old, new) if c is not None)
    return kinds


def _broadcast_digest(ctx: LinkContext, broadcast: ResolverOutput) -> str:
    """One hash over everything the join phase is allowed to read.

    Covers the side tables, the frozen call keys and the broadcast
    resolvers' own output. If any byte differs, every slice's inputs may
    have shifted and nothing can be safely kept.
    """
    rolled = hashlib.sha256()
    for name in ("servicename_id", "service_by_scope_name", "service_by_name",
                 "service_name_of", "module_services", "contract_repos"):
        rolled.update(repr(sorted(
            (k, sorted(v) if isinstance(v, set) else v)
            for k, v in getattr(ctx, name).items())).encode())
    rolled.update(repr(sorted(
        (k, sorted(rules, key=repr))
        for k, rules in ctx.rewrite_routes.items())).encode())
    rolled.update(repr(sorted(ctx.env_values.items(), key=repr)).encode())
    rolled.update(repr(sorted(
        (cid, call) for cid, call in ctx.normalized_calls.items())).encode())
    for edge in broadcast.edges:
        rolled.update(repr((edge.type, edge.source_id, edge.target_id,
                            edge.confidence, tuple(edge.evidence or []))
                           ).encode())
    return rolled.hexdigest()


def _run_broadcast(claims: list, run_id: str, confidence, aliases):
    ctx = LinkContext(run_id, confidence, aliases)
    index = ClaimIndex(claims)
    ctx.known_repos = set(index.repo_ids)
    output = broadcast_pass(index, ctx)
    return ctx, index, output


def relink(claims: list, prior_claims: list, prior: LinkResult, *,
           run_id: str, now: str, confidence: dict, aliases: dict,
           promotions: list) -> LinkResult:
    """A full link's answer at an incremental link's cost.

    Falls back to resolving everything when the broadcast state moved or a
    host resolver is registered (its kinds are unknown here) — counted,
    never silent, because a kept edge under changed inputs is an assertion
    made from stale evidence.
    """
    ctx, index, broadcast = _run_broadcast(claims, run_id, confidence,
                                           aliases)
    prior_ctx, _prior_index, prior_broadcast = _run_broadcast(
        prior_claims, f"{run_id}_prior", confidence, aliases)

    dirty_kinds = changed_kinds(prior_claims, claims)
    registered = any(registered_resolvers().values())
    full_needed = registered or (
        _broadcast_digest(ctx, broadcast)
        != _broadcast_digest(prior_ctx, prior_broadcast))

    if full_needed:
        ctx.count("incremental.full_fallback")
        if registered:
            ctx.count("incremental.registered_resolver")
        else:
            ctx.count("incremental.broadcast_changed")
        rerun = set(RESOLVER_KINDS)
    else:
        rerun = {rid for rid, kinds in RESOLVER_KINDS.items()
                 if kinds & dirty_kinds} | set(_ALWAYS_RERUN)

    rerun_kinds = frozenset().union(
        *(RESOLVER_KINDS[rid] for rid in rerun)) if rerun else frozenset()
    reduced_claims = [c for c in claims if c.kind in rerun_kinds]
    kept_edges = [e for e in prior.edges
                  if getattr(e, "detected_by", "") in
                  set(RESOLVER_KINDS) - rerun]
    ctx.count("incremental.resolvers_rerun", len(rerun))
    ctx.count("incremental.claims_reresolved", len(reduced_claims))
    ctx.count("incremental.edges_kept", len(kept_edges))

    combined = broadcast
    # Only the rerun resolvers, not every resolver over their claims:
    # kinds overlap (r13/r14 both read http), and a non-rerun resolver
    # re-emitting over the reduced slice would duplicate its kept edges.
    # The full fallback passes None — a registered host resolver is not
    # in RESOLVER_KINDS and must still run.
    combined.extend(join_pass(ClaimIndex(reduced_claims), ctx,
                              only=None if full_needed else rerun))
    combined.edges.extend(materialize_pending(ctx))
    # Rollups read the whole graph's edges, kept ones included: a repo
    # dependency derived from an untouched INVOKES is still this run's
    # fact, and rolling up only the re-resolved slice silently drops it —
    # the first divergence the equivalence tests caught.
    combined.edges.extend(
        build_rollups(ctx, combined.edges + kept_edges, now))

    edges = finalize_edges(ctx, combined, promotions) + kept_edges

    new_specs = dedupe_rendezvous(combined)
    new_ids = {spec.node_id for spec in new_specs}
    anchored = {e.target_id for e in kept_edges} \
        | {e.source_id for e in kept_edges}
    kept_specs = [spec for spec in prior.rendezvous
                  if spec.node_id in anchored
                  and spec.node_id not in new_ids]
    rendezvous = new_specs + kept_specs
    annotate_cardinality(rendezvous, edges)

    return LinkResult(
        edges=edges,
        rendezvous=rendezvous,
        services=dedupe_services(combined),
        counters=dict(sorted(ctx.counters.items())),
        repo_ids=sorted(index.repo_ids),
        timings=ctx.timings,
    )
