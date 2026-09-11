"""Which tier priced an edge, and which tiers the config serves.

Extracted from `calibration.py` while adding what its hard-coded section
list could never catch: the R10 and R11 branches were simply absent from
`edge_tier`, and `FLAT_SECTIONS` was a tuple written before those
resolvers existed — so seven served tiers had no measured rows and the
gate saw nothing wrong. A list of sections *is* the hole this module closes:
whoever adds a resolver has to remember to extend it, and the first
deadline forgets. `flat_sections` derives the set from the config itself,
so a new section is gated the moment it exists.
"""

# Sections of confidence.yml that hold numeric values but price nothing:
# the calibration output block, and any future bookkeeping like it.
_NOT_TIER_SECTIONS = frozenset({"measured", "derived"})


def flat_sections(table: dict) -> list[str]:
    """Every config section that serves flat numeric tiers.

    Derived, not listed: a hard-coded tuple predating R10/R11 left their
    seven tiers invisible to the coverage gate. Anything an operator can
    price must be something the gate can miss loudly.
    """
    sections = []
    for section, tiers in (table or {}).items():
        if section in _NOT_TIER_SECTIONS or not isinstance(tiers, dict):
            continue
        if any(isinstance(v, (int, float)) and not isinstance(v, bool)
               for v in tiers.values()):
            sections.append(section)
    return sorted(sections)


def edge_tier(edge, confidence: dict) -> str | None:
    """Map one raw (pre-fusion) linker edge onto the tier that priced it.

    Derived from each resolver's ``ctx.conf("rN", tier)`` call sites. Edges
    that carry no tier discriminator of their own (e.g. R5's stub-side
    RESOLVED_TO, whose paired INVOKES carries the tier) map to None and never
    contribute to a row.
    """
    resolver, match = edge.detected_by, edge.match_type
    if resolver == "resolver.alias@1":
        if edge.type == "RESOLVED_TO":
            return "r0.resolved_to"
        if edge.type == "HAS_ALIAS":
            return "r0.has_alias"
        if edge.type == "BUILT_FROM":
            via = (edge.extra_props.get("via") or [""])[0]
            return {"build_context": "r0.built_from_build_context",
                    "app_name": "r0.built_from_app_name",
                    "descriptor": "r0.built_from_descriptor"}.get(via)
        return None
    if resolver == "resolver.compose@1":
        via = edge.extra_props.get("via") or []
        if "compose_env_host_default" in via:
            return "r1.env_host_default"
        return "r1.env_host" if "compose_env_host" in via else "r1.depends_on"
    if resolver == "resolver.k8s@1":
        if edge.type == "PERMITS_TRAFFIC":
            return "r2.policy"
        return {"selector": "r2.selector_match",
                "k8s_env_host": "r2.env_host",
                "gitops": "r2.built_from_gitops"}.get(match)
    if resolver == "resolver.library@1":
        if edge.type == "PUBLISHES":
            return "r3.publishes"
        if edge.type == "DEPENDS_ON":
            return ("r3.lockfile_resolved" if edge.extra_props.get("resolved")
                    else "r3.manifest_declared")
        return None
    if resolver == "resolver.gateway@1":
        if match == "gateway_route":
            return "r4.route_declared"
        if edge.type == "ROUTES_TO":
            # route_dev and route_declared share match_type "declared". A raw
            # edge's confidence is exactly the served tier value, so the
            # reverse lookup is faithful pre-fusion.
            dev = float((confidence.get("r4") or {}).get("route_dev", -1.0))
            return "r4.route_dev" if edge.confidence == dev \
                else "r4.route_declared"
        return None
    if resolver == "resolver.grpc@1":
        if match == "declared":
            return "r5.declared"
        if match == "grpc_qualified":
            return "r5.exact"
        if match == "grpc_service_name":
            return "r5.service_name"
        if edge.type == "CALLS_SERVICE":
            return "r5.calls_service"
        return None
    if resolver == "resolver.topic@1":
        return {"topic_declared": "r6.declared",
                "topic_literal": "r6.literal",
                "topic_env_resolved": "r6.env_resolved",
                "sns_subscription": "r6.fanout"}.get(match)
    if resolver == "resolver.http@1":
        return {"hint_exact": "r7.hint_exact",
                "hint_template": "r7.hint_template",
                "gateway_exact": "r7.gateway_exact",
                "gateway_template": "r7.gateway_template",
                "declared": "r7.exposes"}.get(match)
    if resolver == "resolver.graphql@1":
        return {"declared": "r8.declared",
                "graphql_federated": "r8.federated",
                "graphql_field_name": "r8.field_name"}.get(match)
    if resolver == "resolver.env@1":
        return "r9.env_resolved" if edge.type == "CALLS_SERVICE" else None
    if resolver == "resolver.dataset@1":
        return {"dataset_declared": "r10.declared",
                "dataset_inferred": "r10.inferred",
                "dataset_literal": "r10.literal"}.get(match)
    if resolver == "resolver.agent@1":
        return {"mcp_registration": "r11.registration",
                "mcp_config": "r11.config",
                "a2a_card": "r11.card",
                "a2a_url": "r11.url_resolved"}.get(match)
    if resolver == "resolver.webhook@1":
        return "r13.registered" if match == "webhook_registration" else None
    if resolver == "resolver.operation@1":
        return {"http_binding": "r14.http_binding",
                "event_schema": "r14.event_schema"}.get(match)
    if resolver == "resolver.owner@1":
        return {"catalog": "r12.catalog",
                "codeowners": "r12.codeowners",
                "observability": "r12.observability"}.get(match)
    return None
