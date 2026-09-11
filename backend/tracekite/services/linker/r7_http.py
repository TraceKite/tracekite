"""R7-lite http matching: qualified-hint tiers only (design §6.2).

hint + exact template 0.95 · hint + positional template 0.85 · intra-repo
precedence. Emits EXPOSES (endpoint -> HttpContract) and INVOKES (call site ->
HttpContract).

Consumer keys arrive already final: naming the callee and rewriting the path
through a gateway's route table happen in the NORMALIZE phase, not here
(architecture §4, invariant I9). What remains is the join itself — look the
key up in the provider index and emit — which is why this resolver can be
partitioned by key without any cross-partition state.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RendezvousSpec, ResolverOutput,
    linker_edge, positional,
)
from tracekite.services.linker.vendors import (
    classify, load_vendors, looks_external,
)
from tracekite.services.linker.normalize import QUALIFIED_HINTS
from tracekite.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)

_VENDOR_CACHE: dict | None = None


def _vendors() -> dict:
    """Catalog loaded once per process; it is operator config, not run state."""
    global _VENDOR_CACHE
    if _VENDOR_CACHE is None:
        _VENDOR_CACHE = load_vendors()
    return _VENDOR_CACHE


def _classify_external(ctx, host: str) -> None:
    """Name an unmatched callee if we can, and count it either way.

    Three outcomes, all declines, none of them silent: a known vendor, an
    unrecognised external host, or a name that is not a host at all — which
    is the interesting one, because an internal service name that matched
    nothing is a genuine missing edge, not a third-party dependency.
    """
    if not looks_external(host):
        ctx.count("r7.unmatched_qualified")
        return
    vendor = classify(host, _vendors())
    if vendor is None:
        ctx.count("r7.external_unknown")
        return
    ctx.count("r7.external_vendor")
    ctx.count(f"r7.vendor.{vendor.name}")

RESOLVER_ID = "resolver.http@1"

# /v1/owners and /v2/owners are different contracts; the version
# is surfaced as a property so skew is queryable, never merged away.
_API_VERSION = re.compile(r"^/(v\d+)(?:/|$)")


@dataclass
class _Provider:
    claim: ClaimRecord
    scope: str
    contract_id: str
    template: str


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    # Read once, up front: the precondition is that NORMALIZE ran, and that
    # must not depend on whether this estate happens to contain a call site.
    calls = ctx.normalized_calls
    providers = _emit_providers(index, ctx, out)

    for claim in index.consumes("http"):
        # NORMALIZE either froze this call's key or declined it, counting the
        # reason as it went. Absence here is therefore already accounted for.
        call = calls.get(claim.id)
        if call is None:
            continue

        # ANY-method providers (a pages/api default export handles every verb)
        # match consumers of any method — the wildcard never beats an exact
        # provider for confidence because tiering keys on the template.
        slot = positional(call.template)
        candidates = (providers.get((call.method, slot), [])
                      + providers.get(("ANY", slot), []))
        named = [p for p in candidates if ctx.canon(p.scope) == call.service]

        if not named:
            # Nothing internal answers this call. Before recording an
            # anonymous decline, ask whether the callee is a third party we
            # recognise — no edge is emitted either way, but "calls
            # Stripe" is a fact and "unmatched" is an absence.
            _classify_external(ctx, call.service)
            continue
        intra = [p for p in named if p.claim.repo_id == claim.repo_id]
        if intra and len(intra) < len(named):
            named = intra
            ctx.count("r7.intra_precedence")

        seen: set[str] = set()
        distinct = []
        for provider in named:
            if provider.contract_id not in seen:
                seen.add(provider.contract_id)
                distinct.append(provider)

        # Guardrail: one ambiguous call site must not fan out across the graph.
        # No partial edges on overflow — emitting a truncated slice would look
        # like a resolved match while hiding the ambiguity (design §3, GitNexus).
        if len(distinct) > ctx.fanout_cap:
            ctx.count("r7.fanout_exceeded")
            logger.info("R7 dropped %s: %d candidate contracts exceeds cap %d",
                        claim.key, len(distinct), ctx.fanout_cap)
            continue

        for provider in distinct:
            exact = provider.template == call.template
            if call.gateway_resolved:
                tier = "gateway_exact" if exact else "gateway_template"
            else:
                tier = "hint_exact" if exact else "hint_template"
            confidence = ctx.conf("r7", tier)
            if call.gateway_hops > 1:
                # A chained resolution is only as good as EVERY table in the
                # chain, so the tier compounds per hop — the same conservative
                # product F2 applies to paths. One hop is the tier's own
                # meaning and is never discounted.
                confidence = round(confidence ** call.gateway_hops, 4)
            extra = {"via": ["http"]}
            if call.via_gateway:
                extra["via"] = ["http", "gateway_rewrite"]
            if call.gateway_hops > 1:
                extra["gateway_hops"] = call.gateway_hops
            if call.route_repo and call.route_repo != claim.repo_id:
                # The route lives in another repo, so its evidence path must
                # not be resolved against this edge's source repo -- a deep
                # link built that way points at a file that isn't there.
                extra["route_repo"] = call.route_repo
            if call.hint_source == "config" and claim.hint_source not in QUALIFIED_HINTS:
                # Records that the callee came from config indirection rather
                # than a literal in the source, so the evidence trail is honest
                # about how the edge was established.
                extra["via"] = extra["via"] + ["config_host"]
            # A gateway-resolved edge is only as good as the route that
            # justified it, so the route's own file:line rides along with the
            # call site's. Both halves of the reasoning stay clickable.
            evidence = claim.evidence + list(call.route_evidence)
            # A component's call is the same join priced the same way; the
            # TYPE is what changes, so a UI can be filtered in or out of a
            # blast radius without re-deriving anything.
            edge_type = "UI_CALLS" if claim.attrs.get("ui") else "INVOKES"
            if claim.attrs.get("schedule"):
                extra["schedule"] = str(claim.attrs["schedule"])
            if claim.attrs.get("channel"):
                extra["channel"] = str(claim.attrs["channel"])
            if claim.attrs.get("flag"):
                # This call only happens when the flag is on. The
                # condition rides the edge; the edge itself is real wiring
                # and prices normally.
                extra["condition"] = f"flag:{claim.attrs['flag']}"
            if edge_type == "UI_CALLS":
                ctx.count("r7.ui_calls")
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, edge_type, claim.evidence_node_id,
                provider.contract_id, source_label="GraphNode",
                target_label="HttpContract", confidence=confidence,
                match_type=tier, evidence=evidence, claim_key=claim.key,
                source_repo=claim.repo_id, target_repo=provider.claim.repo_id,
                origin="matched", extra=extra,
            ))
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, provider.contract_id,
                source_label="ContractClaim", target_label="HttpContract",
                confidence=confidence, match_type=tier,
                evidence=claim.evidence, claim_key=claim.key,
                source_repo=claim.repo_id, origin="matched",
            ))
            ctx.count("r7.invokes")
    return out


def contract_lookup(index: ClaimIndex, ctx: LinkContext) -> dict:
    """(method, positional template) -> [(contract_id, repo, scope)].

    The lookup half of `_emit_providers`, without the minting: R13 joins
    webhook callbacks onto the same contract space R7 owns, and rebuilding
    the id format there would be a second canonicaliser wearing a helper's
    name (I4).
    """
    table: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    for claim in index.provides("http"):
        method, _, template = claim.key.partition(":")
        scope = ctx.scope_for(claim.repo_id, claim.primary_path)
        table.setdefault((method, positional(template)), []).append(
            (rid.http_contract_id(scope, method, template), claim.repo_id,
             scope))
    return table


def _emit_providers(index: ClaimIndex, ctx: LinkContext,
                    out: ResolverOutput) -> dict[tuple[str, str], list[_Provider]]:
    providers: dict[tuple[str, str], list[_Provider]] = defaultdict(list)
    seen_contracts: set[str] = set()
    for claim in index.provides("http"):
        method, _, template = claim.key.partition(":")
        scope = ctx.scope_for(claim.repo_id, claim.primary_path)
        contract_id = rid.http_contract_id(scope, method, template)
        provider = _Provider(claim=claim, scope=scope, contract_id=contract_id,
                             template=template)
        providers[(method, positional(template))].append(provider)
        ctx.contract_repos[contract_id].add(claim.repo_id)

        if contract_id not in seen_contracts:
            seen_contracts.add(contract_id)
            version = _API_VERSION.match(template)
            props = {
                "method": method, "path_template": template,
                "positional_template": positional(template),
                "service_scope": scope,
                "repo_ids": sorted(ctx.contract_repos[contract_id]),
            }
            if version:
                props["api_version"] = version.group(1)
            if claim.attrs.get("deprecated"):
                props["deprecated"] = True
                ctx.count("r7.deprecated_contracts")
            if claim.attrs.get("channel"):
                props["channel"] = str(claim.attrs["channel"])
                ctx.count("r7.channel_contracts")
            out.rendezvous.append(RendezvousSpec("HttpContract", contract_id,
                                                 props))
            ctx.count("r7.contracts")

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, contract_id,
            source_label="ContractClaim", target_label="HttpContract",
            confidence=ctx.conf("r7", "exposes"), match_type="declared",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, origin="declared",
        ))
        if claim.evidence_node_id:
            out.edges.append(linker_edge(
                ctx, RESOLVER_ID, "EXPOSES", claim.evidence_node_id, contract_id,
                source_label="GraphNode", target_label="HttpContract",
                confidence=ctx.conf("r7", "exposes"), match_type="declared",
                evidence=claim.evidence, claim_key=claim.key,
                source_repo=claim.repo_id, origin="declared",
                extra={"via": ["annotation"]},
            ))
    return providers
