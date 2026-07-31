"""R13 webhooks: a registered callback is a delivery contract.

A webhook registration is code in one repository promising that another
repository's endpoint will be called later — cross-repo coupling with no
call site at delivery time, which is why it needs its own join rather
than falling out of HTTP extraction.

The join is deliberately strict: the callback's host must name a service
whose OWN declared route matches the callback path. A registration whose
receiver has no such route is declined and counted — the callback might
point at a dead path, an external system, or a typo, and asserting any of
those as a live delivery contract is an invented edge with a timer on it.
"""

import logging

from adduce.services.linker.base import (
    ClaimIndex, LinkContext, ResolverOutput, linker_edge, positional,
)
from adduce.services.linker.r7_http import contract_lookup

logger = logging.getLogger(__name__)

RESOLVER_ID = "resolver.webhook@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    claims = index.consumes("webhook")
    if not claims:
        return out
    lookup = contract_lookup(index, ctx)

    for claim in claims:
        _, _, rest = claim.key.partition(":")
        method, _, template = rest.partition(":") if ":" in rest \
            else ("POST", "", rest)
        receiver = ctx.canon(claim.service_hint)
        candidates = [
            (cid, repo) for cid, repo, scope in
            lookup.get((method or "POST", positional(template)), [])
            if scope == receiver]
        if not candidates:
            ctx.count("r13.receiver_unmatched")
            continue
        if len(candidates) > 1:
            ctx.count("r13.receiver_ambiguous")
            continue

        contract_id, provider_repo = candidates[0]
        source = ctx.module_service_name(claim.repo_id, claim.primary_path)
        source_id = ctx.service_by_name.get(ctx.canon(source or ""))
        if source_id is None:
            # The registrar's own service identity is the edge's source;
            # without it there is nothing honest to hang the edge from.
            ctx.count("r13.registrar_unminted")
            continue

        confidence = ctx.conf("r13", "registered")
        extra = {"via": ["webhook"]}
        deliverer = str(claim.attrs.get("deliverer") or "")
        if deliverer and len(deliverer) >= 4:
            extra["deliverer"] = deliverer
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "REGISTERS_WEBHOOK", source_id, contract_id,
            source_label="Service", target_label="HttpContract",
            confidence=confidence, match_type="webhook_registration",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, target_repo=provider_repo,
            origin="declared", extra=extra,
        ))
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id, contract_id,
            source_label="ContractClaim", target_label="HttpContract",
            confidence=confidence, match_type="webhook_registration",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, origin="declared",
        ))
        ctx.count("r13.registered")
    return out
