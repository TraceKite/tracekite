"""R4 gateway: route claims become Service:Gateway -ROUTES_TO-> target, and
the rewrite table R7 consults (design §6.2). Unresolved targets stay
ServiceName dead-ends — honest."""

from evigraph.services.linker.base import (
    ClaimIndex, LinkContext, ResolverOutput, RouteRule, ServiceSpec, linker_edge,
)

RESOLVER_ID = "resolver.gateway@1"


def resolve(index: ClaimIndex, ctx: LinkContext) -> ResolverOutput:
    out = ResolverOutput()
    gateway_ids: set[str] = set()

    for claim in index.consumes("route"):
        target_name = ctx.canon(claim.attrs.get("target"))
        prefix = claim.attrs.get("path_prefix") or "/"
        if not target_name:
            ctx.count("r4.no_target")
            continue

        # File-based gateways (an nginx.conf, a next.config) carry no service
        # hint of their own; the module owning the file is the gateway.
        gw_name = ctx.canon(claim.service_hint) or ctx.canon(
            ctx.module_service_name(claim.repo_id, claim.primary_path) or "")
        rule = RouteRule(
            prefix=prefix, strip_prefix=int(claim.attrs.get("strip_prefix") or 0),
            rewrite_pattern=str(claim.attrs.get("rewrite_path") or ""),
            rewrite_replacement=str(claim.attrs.get("rewrite_replacement") or ""),
            target_name=target_name, evidence=claim.evidence,
            repo_id=claim.repo_id,
        )
        if gw_name:
            ctx.rewrite_routes[gw_name].append(rule)

        gw_service = ctx.service_by_name.get(gw_name) if gw_name else None
        target = _target_endpoint(ctx, target_name)
        if target is None:
            ctx.count("r4.dead_end_no_servicename")
            continue
        if target[0] == "ServiceName":
            ctx.count("r4.dead_end_targets")

        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "RESOLVED_TO", claim.id,
            ctx.servicename_id.get(("discovery", target_name), target[1]),
            source_label="ContractClaim", target_label="ServiceName",
            confidence=ctx.conf("r4", "route_declared"), match_type="gateway_route",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, origin="declared",
        ))

        if gw_service is None:
            ctx.count("r4.gateway_unminted")
            continue
        gateway_ids.add(gw_service)
        # Dev-only proxies (vite/webpack devServer) are real wiring but only
        # hold on a developer laptop, so they get their own tier.
        tier = "route_dev" if claim.attrs.get("dev") else "route_declared"
        confidence = ctx.conf("r4", tier)
        extra = {"path_prefix": prefix, "strip_path": rule.strip_prefix,
                 "rewrite_to": rule.rewrite_pattern, "via": ["gateway_config"],
                 "gateway_kind": str(claim.attrs.get("gateway_kind") or "")}
        if claim.attrs.get("host"):
            extra["match_host"] = str(claim.attrs["host"])
        if claim.attrs.get("weight") is not None:
            extra["weight"] = claim.attrs.get("weight")
        out.edges.append(linker_edge(
            ctx, RESOLVER_ID, "ROUTES_TO", gw_service, target[1],
            source_label="Service", target_label=target[0],
            confidence=confidence, match_type="declared",
            evidence=claim.evidence, claim_key=claim.key,
            source_repo=claim.repo_id, origin="declared",
            extra=extra,
        ))
        ctx.count("r4.routes")

    for service_id in sorted(gateway_ids):
        out.services.append(ServiceSpec(
            service_id=service_id, name=ctx.service_name_of.get(service_id, ""),
            is_gateway=True,
            repo_ids=sorted(ctx.service_repos.get(service_id, set())),
        ))
    return out


def _target_endpoint(ctx: LinkContext, name: str) -> tuple[str, str] | None:
    service_id = ctx.service_by_name.get(name)
    if service_id:
        return "Service", service_id
    sn_id = ctx.servicename_id.get(("discovery", name))
    if sn_id:
        return "ServiceName", sn_id
    return None
