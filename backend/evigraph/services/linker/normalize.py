"""NORMALIZE phase: freeze every rendezvous key before the join
(architecture §4, decision AD8, invariant I9).

Three operations change a consumer claim's rendezvous key: a gateway strips a
path prefix before forwarding, an alias renames the target service, and config
indirection supplies a host the source file never mentions. Until they have
run, a call site's key is provisional.

That matters more than it looks. The join is a group-by on the rendezvous key,
so claims are routed to a partition by hashing it. A claim whose key is
rewritten *after* that routing sits in a partition it does not belong to, finds
no counterpart there, and yields no edge — silently, which for a tool whose
whole claim is "every edge cites its evidence" is the worst available failure.
Single-threaded the bug is invisible; it appears the moment a second worker
does.

So key-rewriting is lifted out of the resolvers and into this phase. It runs
after the resolvers that contribute broadcast state (r2/r0 aliases, r4 route
tables) and before any resolver that joins on a key. It reads broadcast state
and the claim index; it writes nothing but counters, so it parallelises exactly
as the map phase does.

A call this phase cannot qualify produces no record. The decline is counted
here, so the joining resolver simply finds nothing — declines stay data, never
silence (invariant I5).
"""

import logging
from collections import defaultdict

from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, NormalizedCall,
)
from evigraph.services.linker.path_algebra import apply_rule, resolve_chain
from evigraph.utils.canonical import squash_separators

logger = logging.getLogger(__name__)

# Hint sources that already name the callee, so no recovery is needed.
QUALIFIED_HINTS = ("discovery", "host", "config", "gateway_route")


def _env_host_services(index: ClaimIndex) -> dict[tuple[str, str], str]:
    """(repo, ENV_KEY) -> service host, from compose `env_host` claims.

    Compose declares `CAPABILITY_REGISTRY_URL: http://capability-registry:8080`
    and the ingest already turns that into a svcname claim carrying both the
    env key and the host. That is one half of a call's identity.
    """
    mapping: dict[tuple[str, str], str] = {}
    for claim in index.consumes("svcname"):
        if claim.attrs.get("via") != "env_host":
            continue
        env_key = str(claim.attrs.get("env_key") or "")
        if env_key and claim.service_hint:
            mapping[(claim.repo_id, env_key.upper())] = claim.service_hint
    return mapping


def _env_reads_by_dir(index: ClaimIndex) -> dict[tuple[str, str], set[str]]:
    """(repo, directory) -> ENV_KEYs read by code in it, from cfgread claims."""
    reads: dict[tuple[str, str], set[str]] = defaultdict(set)
    for claim in index.kind("cfgread"):
        path = claim.primary_path or ""
        if not path:
            continue
        env_key = claim.key.rpartition(":")[2].upper()
        if not env_key:
            continue
        parts = path.split("/")
        # Index every ancestor directory: the config module that reads the env
        # var is rarely the module that makes the call, but they share a root.
        for depth in range(1, len(parts)):
            reads[(claim.repo_id, "/".join(parts[:depth]))].add(env_key)
    return reads


def _qualify_from_config(claim: ClaimRecord, ctx: LinkContext,
                         env_services: dict[tuple[str, str], str],
                         env_reads: dict[tuple[str, str], set[str]]) -> str | None:
    """Name the callee of a path-only call site, or decline.

    The host never appears in the source — it is injected from configuration —
    so the call site alone cannot say who it talks to. What the code DOES say
    is which config keys it reads, and compose says which service each of those
    keys points at. Joining the two identifies the callee without guessing.

    Ambiguity is declined, not broken arbitrarily: a module reading two service
    URLs could be calling either. The base-variable name (`self._registry_url`
    -> `registry`) is used only to break such a tie, never to name a service on
    its own.
    """
    # Squashed like the names it is compared against. `self._billing_service_url`
    # yields `billing_service`, and the service is spelled `billing-service`:
    # comparing raw-vs-squashed can never match a multi-word name, which
    # silently disables this tie-break for exactly the services whose names
    # are distinctive enough to make it safe. Squashing both sides only
    # erases separator differences — a name that matches two services still
    # matches two, and is still declined.
    base_var = squash_separators(str(claim.attrs.get("base_var") or ""))

    path = claim.primary_path or ""
    parts = path.split("/") if path else []
    ambiguous_scope = False
    for depth in range(len(parts) - 1, 0, -1):
        keys = env_reads.get((claim.repo_id, "/".join(parts[:depth])))
        if not keys:
            continue
        candidates = {env_services[(claim.repo_id, k)]
                      for k in keys if (claim.repo_id, k) in env_services}
        if not candidates:
            continue
        if len(candidates) == 1:
            ctx.count("r7.qualified_by_config")
            return next(iter(candidates))
        if base_var:
            narrowed = [s for s in candidates if base_var in squash_separators(s)]
            if len(narrowed) == 1:
                ctx.count("r7.qualified_by_config_var")
                return narrowed[0]
        # Ambiguous at this scope. Do NOT stop here: the walk climbs toward the
        # repo root, where nearly every env var is in scope and ambiguity is
        # guaranteed. Falling through lets the stricter variable-name rule
        # below still identify the callee.
        ambiguous_scope = True
        break

    # Match the base variable against the repo's declared service URLs. Still
    # evidence-based — the name must single out one env var that compose
    # actually points at a service — and it is the only signal left when the
    # settings module lives in a sibling tree, or the service is written in a
    # language whose config reads are not extracted.
    if base_var and len(base_var) >= 4:
        matches = {
            service for (repo, env_key), service in env_services.items()
            if repo == claim.repo_id and base_var in squash_separators(env_key)
        }
        if len(matches) == 1:
            ctx.count("r7.qualified_by_var_only")
            return next(iter(matches))
        if matches:
            ctx.count("r7.var_only_ambiguous")
            return None
    if ambiguous_scope:
        ctx.count("r7.config_scope_ambiguous")
    return None


def _qualify_from_gateway(
        ctx: LinkContext, template: str,
        repo_id: str) -> tuple[str, str, list[str], str, int] | None:
    """Name the callee of a gateway-relative path, or decline.

    A browser or edge client calls `/api/vet/vets`: no host, no env var, so
    neither the literal-host rule nor config indirection can say who answers.
    But the gateway's own route table -- already extracted by R4 -- says
    `/api/vet` routes to vets-service and strips two segments, leaving `/vets`,
    which is exactly what that service declares. Joining the two is evidence
    (the gateway's config), not a guess.

    Without this the two halves of every through-gateway call are written in
    different path spaces and can never rendezvous: consumers hold the public
    path and providers hold the service-local one.

    Returns (target service, rewritten path, route evidence, route repo,
    hops).
    """
    matches = [rule
               for rules in ctx.rewrite_routes.values()
               for rule in rules
               if rule.prefix and template.startswith(rule.prefix)]
    if not matches:
        return None

    # Longest prefix wins, as it does within a single gateway's table.
    longest = max(len(rule.prefix) for rule in matches)
    finalists = [rule for rule in matches if len(rule.prefix) == longest]

    # Route tables are keyed by gateway name, so two repos declaring the same
    # gateway share one table. A route the caller's OWN repo declares describes
    # the caller's deployment; another repo's route only happens to share a
    # name. Prefer the local one, mirroring the intra-repo precedence R7
    # already applies to providers.
    local = [rule for rule in finalists if rule.repo_id == repo_id]
    if local and len(local) < len(finalists):
        finalists = local
        ctx.count("r7.gateway_intra_precedence")

    # Two gateways claiming the same prefix for different services is genuine
    # ambiguity -- decline rather than pick, since a wrong call edge costs the
    # user a verification they did not know they needed.
    if len({rule.target_name for rule in finalists}) > 1:
        ctx.count("r7.gateway_prefix_ambiguous")
        return None

    rule = finalists[0]
    rewritten = apply_rule(rule, template)
    if rewritten is None:
        ctx.count("r7.gateway_rewrite_invalid")
        return None
    ctx.count("r7.qualified_by_gateway")

    # The first hop may land on ANOTHER gateway (edge → mesh → service):
    # follow its tables too, so the rendezvous key is final, not one hop
    # closer. A cycle refuses the whole call.
    chain = resolve_chain(ctx, ctx.canon(rule.target_name), rewritten)
    if chain is None:
        return None
    evidence = list(rule.evidence or []) + chain.evidence()
    return (chain.service, chain.template, evidence, rule.repo_id,
            1 + chain.hops)


def normalize_http_calls(index: ClaimIndex,
                         ctx: LinkContext) -> dict[str, NormalizedCall]:
    """Resolve every HTTP call site to its final (service, method, template).

    Requires the broadcast state to be complete: `ctx.rewrite_routes` from R4
    and the alias table from the LinkContext constructor. Reads nothing that a
    joining resolver writes, which is what lets this run as one parallel pass.
    """
    env_services = _env_host_services(index)
    env_reads = _env_reads_by_dir(index)
    normalized: dict[str, NormalizedCall] = {}

    for claim in index.consumes("http"):
        key = claim.key
        if not key.startswith("httpcall:"):
            continue
        method, _, template = key[len("httpcall:"):].partition(":")
        hint_name = claim.service_hint
        hint_source = claim.hint_source
        route_evidence: list[str] = []
        route_repo = ""
        gateway_resolved = False
        hops = 0

        if hint_source not in QUALIFIED_HINTS or not hint_name:
            # A dependency-injected client has no literal host, so the call
            # site is path-only. Recover the callee from configuration before
            # giving up — this is the difference between a container-level
            # dependency and an actual call edge.
            hint_name = _qualify_from_config(claim, ctx, env_services, env_reads)
            if hint_name:
                hint_source = "config"
            else:
                # Last resort: the path itself may be gateway-relative, in
                # which case the gateway's route table names the callee.
                hit = _qualify_from_gateway(ctx, template, claim.repo_id)
                if hit is None:
                    ctx.count("r7.unqualified")
                    continue
                hint_name, template, route_evidence, route_repo, hops = hit
                hint_source = "gateway_route"
                gateway_resolved = True

        # A call site with no node to hang an edge from can never rendezvous,
        # so it is declined here rather than carried through the join.
        if claim.evidence_node_id is None:
            ctx.count("r7.no_call_site_node")
            continue

        if gateway_resolved:
            # Already chained through the route tables to its final target.
            service, via_gateway = ctx.canon(hint_name), True
        else:
            # The callee is named, but the name may be a gateway (or a chain
            # of them): follow its tables until the path lands.
            chain = resolve_chain(ctx, ctx.canon(hint_name), template)
            if chain is None:
                continue                     # cycle: counted in the algebra
            service, template = chain.service, chain.template
            via_gateway = chain.hops > 0
            hops = chain.hops
            route_evidence = chain.evidence()
            route_repo = chain.steps[0].repo_id if chain.steps else ""

        normalized[claim.id] = NormalizedCall(
            service=service, method=method, template=template,
            hint_source=hint_source, via_gateway=via_gateway,
            gateway_resolved=gateway_resolved,
            route_evidence=tuple(route_evidence), route_repo=route_repo,
            gateway_hops=hops,
        )

    ctx.count("normalize.http_calls", len(normalized))
    return normalized
