"""R1 compose topology: depends_on/links/env-hosts within a compose project
scope become service-service CALLS_SERVICE edges (design §6.2, 0.95-0.98)."""

from tracekite.services.linker.base import ClaimIndex, LinkContext, ResolverOutput, linker_edge

RESOLVER_ID = "resolver.compose@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    for claim in index.consumes("svcname"):
        scope, _, target_name = claim.key.partition(":")
        if scope == "discovery":
            continue
        from_name = ctx.canon(claim.attrs.get("from"))
        if not from_name:
            ctx.count("r1.no_consumer_identity")
            continue
        providers = [c for c in index.for_key("svcname", claim.key)
                     if c.direction == "provides"]
        if not providers:
            ctx.count("r1.unmatched")
            continue

        target_name = ctx.canon(target_name)
        source = _endpoint(ctx, scope, from_name)
        target = _endpoint(ctx, scope, target_name)
        # Counted, not silent: these three were one bare `continue`, so a
        # compose topology that resolved nothing looked identical to one with
        # nothing to resolve. A decline is recorded data (invariant I5).
        if source is None:
            ctx.count("r1.consumer_not_minted")
            continue
        if target is None:
            ctx.count("r1.target_not_minted")
            continue
        if source[1] == target[1]:
            ctx.count("r1.calls_self")
            continue

        via = claim.attrs.get("via", "depends_on")
        tier = {"env_host": "env_host",
                "env_host_default": "env_host_default"}.get(via, "depends_on")
        confidence = ctx.conf("r1", tier)
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "CALLS_SERVICE", source[1], target[1],
            source_label=source[0], target_label=target[0],
            confidence=confidence, match_type="topology",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id,
            target_repo=providers[0].repo_id, origin="matched",
            extra={"via": [f"compose_{via}"]},
        ))
        ctx.count("r1.calls_service")
    return out


def _endpoint(ctx: LinkContext, scope: str, name: str) -> tuple[str, str] | None:
    service_id = ctx.service_by_scope_name.get((scope, name))
    if service_id:
        return "Service", service_id
    sn_id = ctx.servicename_id.get((scope, name))
    if sn_id:
        return "ServiceName", sn_id
    return None
