"""C8/E1: the path algebra, and two-hop chains producing one edge.

The unresolvable cases matter as much as the resolvable ones: a cycle in
route tables refuses the whole call, a chain past the cap stops at the
last sound hop, and a same-length prefix tie naming two targets matches
nothing — the old code silently took whichever tied rule parsed first.
"""

from tracekite.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, RouteRule, load_confidence,
)
from tracekite.services.linker.engine import link
from tracekite.services.linker.path_algebra import (
    apply_rule, match_table, resolve_chain,
)


def rule(prefix, target, strip=0, pattern="", replacement="", repo="repo_gw"):
    return RouteRule(prefix=prefix, strip_prefix=strip,
                     rewrite_pattern=pattern,
                     rewrite_replacement=replacement, target_name=target,
                     evidence=[f"{repo}/gateway.yml:1"], repo_id=repo)


def ctx():
    return LinkContext("linkrun_test", load_confidence(), {})


class TestApplyRule:
    def test_prefix_strip(self):
        assert apply_rule(rule("/api/vet", "vets", strip=2),
                          "/api/vet/vets") == "/vets"

    def test_regex_rewrite_applies_after_strip(self):
        # nginx: rewrite ^/orders/(.*)$ /v1/$1 — parsed and carried since
        # r4 landed, applied for the first time here.
        r = rule("/api", "orders", strip=1,
                 pattern=r"^/orders/(.*)$", replacement=r"/v1/\1")
        assert apply_rule(r, "/api/orders/list") == "/v1/list"

    def test_versioned_prefix_keeps_the_version(self):
        assert apply_rule(rule("/api", "orders", strip=1),
                          "/api/v2/orders") == "/v2/orders"

    def test_broken_pattern_claims_nothing(self):
        r = rule("/api", "orders", pattern="(unclosed", replacement="/x")
        assert apply_rule(r, "/api/orders") is None

    def test_non_matching_prefix_claims_nothing(self):
        assert apply_rule(rule("/other", "x"), "/api/orders") is None


class TestMatchTable:
    def test_longest_prefix_wins(self):
        table = [rule("/api", "generic"), rule("/api/orders", "orders")]
        assert match_table(table, "/api/orders/1").target_name == "orders"

    def test_same_length_tie_is_ambiguous_not_first_wins(self):
        table = [rule("/api", "orders"), rule("/api", "billing")]
        assert match_table(table, "/api/x") == "ambiguous"


class TestChains:
    def test_two_hops_land_on_the_service(self):
        c = ctx()
        c.rewrite_routes["edge"] = [rule("/api", "mesh", strip=1)]
        c.rewrite_routes["mesh"] = [rule("/orders", "orders-service",
                                         strip=1, repo="repo_mesh")]
        chain = resolve_chain(c, "edge", "/api/orders/list")
        assert chain.service == "orders-service"
        assert chain.template == "/list"
        assert chain.hops == 2
        assert chain.evidence() == ["repo_gw/gateway.yml:1",
                                    "repo_mesh/gateway.yml:1"]

    def test_cycle_refuses_the_whole_call(self):
        c = ctx()
        c.rewrite_routes["a"] = [rule("/x", "b")]
        c.rewrite_routes["b"] = [rule("/x", "a")]
        assert resolve_chain(c, "a", "/x/1") is None
        assert c.counters["r7.gateway_route_cycle"] == 1

    def test_depth_cap_stops_at_the_last_sound_hop(self):
        c = ctx()
        for i in range(5):
            c.rewrite_routes[f"g{i}"] = [rule("/x", f"g{i + 1}")]
        chain = resolve_chain(c, "g0", "/x/1", max_hops=3)
        assert chain.hops == 3 and chain.service == "g3"
        assert c.counters["r7.gateway_chain_too_deep"] == 1

    def test_mid_chain_ambiguity_stops_and_counts(self):
        c = ctx()
        c.rewrite_routes["edge"] = [rule("/api", "mesh", strip=1)]
        c.rewrite_routes["mesh"] = [rule("/orders", "a"),
                                    rule("/orders", "b")]
        chain = resolve_chain(c, "edge", "/api/orders")
        assert chain.service == "mesh" and chain.hops == 1
        assert c.counters["r7.gateway_chain_ambiguous"] == 1


def claim(kind, direction, key, repo, hint=None, hint_source="none",
          attrs=None, evidence=None, enode=None):
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=True, attrs=attrs or {},
        evidence=evidence or [f"{repo}/src/app.py:1"],
        evidence_node_id=enode, evidence_node_type="",
    )


def two_hop_estate():
    """Browser calls /api/orders/list; edge strips /api to the mesh; the
    mesh strips /orders to orders-service, which provides GET /list."""
    return [
        claim("svcname", "provides", "proj:edge", repo="repo_edge",
              attrs={"source": "compose", "build_context": "."}),
        claim("route", "consumes", "/api→svcname:mesh",
              repo="repo_edge", hint="edge", hint_source="gateway_route",
              attrs={"target": "mesh", "path_prefix": "/api",
                     "strip_prefix": 1},
              evidence=["repo_edge/nginx.conf:3"]),
        claim("svcname", "provides", "proj:mesh", repo="repo_mesh",
              attrs={"source": "compose", "build_context": "."}),
        claim("route", "consumes", "/orders→svcname:orders-service",
              repo="repo_mesh", hint="mesh", hint_source="gateway_route",
              attrs={"target": "orders-service", "path_prefix": "/orders",
                     "strip_prefix": 1},
              evidence=["repo_mesh/mesh.yml:7"]),
        claim("svcname", "provides", "proj:orders-service",
              repo="repo_orders",
              attrs={"source": "compose", "build_context": "."}),
        claim("http", "provides", "GET:/list", repo="repo_orders",
              evidence=["repo_orders/src/api.py:5"], enode="node:endpoint"),
        claim("svcname", "provides", "proj:web", repo="repo_web",
              attrs={"source": "compose", "build_context": "."}),
        claim("http", "consumes", "httpcall:GET:/api/orders/list",
              repo="repo_web", enode="node:callsite",
              evidence=["repo_web/src/api.ts:41"]),
    ]


class TestE1TwoHopsOneEdge:
    def test_two_hop_chain_produces_one_edge_citing_both_tables(self):
        result = link(two_hop_estate(), now="2026-01-01T00:00:00+00:00",
                      aliases={}, promotions=[])
        [invoke] = [e for e in result.edges if e.type == "INVOKES"]
        assert invoke.target_id.endswith("orders-service:GET:/list")
        # Both route tables are the receipt: the call site alone proves
        # nothing about where /api/orders/list lands.
        assert "repo_edge/nginx.conf:3" in invoke.evidence
        assert "repo_mesh/mesh.yml:7" in invoke.evidence
        assert invoke.extra_props.get("gateway_hops") == 2
        # gateway tier compounded once per hop: only as good as EVERY
        # table in the chain.
        tier = load_confidence()["r7"]["gateway_exact"]
        assert invoke.confidence == round(tier ** 2, 4)

    def test_single_hop_pricing_is_unchanged(self):
        estate = [c for c in two_hop_estate()
                  if c.repo_id != "repo_mesh"] + [
            claim("http", "provides", "GET:/orders/list", repo="repo_mesh2",
                  evidence=["repo_mesh2/src/api.py:5"],
                  enode="node:endpoint"),
            claim("svcname", "provides", "proj:mesh", repo="repo_mesh2",
                  attrs={"source": "compose", "build_context": "."}),
        ]
        result = link(estate, now="2026-01-01T00:00:00+00:00", aliases={},
                      promotions=[])
        [invoke] = [e for e in result.edges if e.type == "INVOKES"]
        assert invoke.confidence == load_confidence()["r7"]["gateway_exact"]
        assert "gateway_hops" not in invoke.extra_props
