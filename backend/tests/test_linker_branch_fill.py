"""PR-boundary branch fill for the pure-python linker resolvers.

Every test here targets a specific uncovered guard clause / tier fallback /
counter branch in base.py, r0_alias.py, r1_compose.py, r4_gateway.py,
r7_http.py and rollups.py. Behaviour (edges/ids/counters), not mere
execution, is asserted throughout. Fixture style mirrors
tests/test_linker_resolvers.py and tests/test_linker_matching.py.
"""

import os
from unittest.mock import patch

import pytest

from adduce.models.graph_models import GraphEdge
from adduce.services.linker import normalize
from adduce.services.linker.normalize import normalize_http_calls
from adduce.services.linker import r0_alias, r1_compose, r4_gateway, r7_http
from adduce.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, ResolverOutput, RendezvousSpec,
    ServiceSpec, fuse_edges, linker_edge, load_aliases, load_confidence,
)
from adduce.services.linker.rollups import build_rollups


def claim(kind, direction, key, repo="repo_a", hint=None, hint_source="none",
          matchable=True, attrs=None, evidence=None, enode=None, etype=""):
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=matchable, attrs=attrs or {},
        evidence=evidence if evidence is not None
        else [f"{repo}/src/App.java:10"],
        evidence_node_id=enode, evidence_node_type=etype,
    )


def app_name(name, repo, module=None):
    path = f"{module or name}/src/main/resources/application.yml:2"
    return claim("svcname", "provides", f"discovery:{name}", repo=repo,
                 attrs={"source": "spring.application.name"}, evidence=[path])


def _provider(template, repo="repo_prov", module="customers-service"):
    return claim("http", "provides", f"GET:{template}", repo=repo,
                 evidence=[f"{module}/src/main/java/OwnerResource.java:40"],
                 enode=f"{repo}:endpoint:GET:{template}", etype="ApiEndpoint")


def _consumer(template, hint, repo="repo_cons", source="discovery", enode=None,
              etype="File"):
    return claim("http", "consumes", f"httpcall:GET:{template}", repo=repo,
                 hint=hint, hint_source=source,
                 evidence=[f"{repo}/src/main/java/Client.java:12"],
                 enode=enode if enode is not None else f"{repo}:file:Client.java",
                 etype=etype)


def ctx():
    return LinkContext("linkrun_test", load_confidence(), {})


# --------------------------------------------------------------------------
# base.py
# --------------------------------------------------------------------------
class TestBase:
    def test_primary_path_empty_evidence(self):
        # base.py:41 -- primary_path returns "" when evidence is empty.
        c = claim("svcname", "provides", "discovery:x", evidence=[])
        assert c.evidence == []
        assert c.primary_path == ""

    def test_primary_path_nonempty(self):
        c = claim("svcname", "provides", "discovery:x",
                  evidence=["a/b/File.java:12"])
        assert c.primary_path == "a/b/File.java"

    def test_repo_ids_property(self):
        # base.py:68 -- ClaimIndex.repo_ids set comprehension.
        index = ClaimIndex([
            claim("svcname", "provides", "discovery:x", repo="r1"),
            claim("svcname", "provides", "discovery:y", repo="r2"),
            claim("svcname", "provides", "discovery:z", repo="r1"),
        ])
        assert index.repo_ids == {"r1", "r2"}

    def test_resolver_output_extend(self):
        # base.py:103-105 -- ResolverOutput.extend merges all three lists.
        a = ResolverOutput(
            rendezvous=[RendezvousSpec("ServiceName", "n1", {})],
            services=[ServiceSpec("s1", "svc1")],
            edges=[],
        )
        e = linker_edge(ctx(), "resolver.alias@1", "RESOLVED_TO", "src", "tgt",
                        source_label="A", target_label="B", confidence=0.9,
                        match_type="alias", evidence=["x:1"])
        b = ResolverOutput(
            rendezvous=[RendezvousSpec("ServiceName", "n2", {})],
            services=[ServiceSpec("s2", "svc2")],
            edges=[e],
        )
        a.extend(b)
        assert [r.node_id for r in a.rendezvous] == ["n1", "n2"]
        assert [s.service_id for s in a.services] == ["s1", "s2"]
        assert a.edges == [e]

    def test_linkcontext_alias_expansion(self):
        # base.py:114-116 -- alias canonicalisation across canonical + names.
        c = LinkContext("run", load_confidence(),
                        {"Payments": ["billing", "Pay-Svc"]})
        assert c.canon("PAYMENTS") == "payments"
        assert c.canon("billing") == "payments"
        assert c.canon("pay-svc") == "payments"
        # unknown name falls through unchanged (lower-cased)
        assert c.canon("Unknown") == "unknown"

    def test_linkcontext_alias_none_names(self):
        # base.py:115-116 -- `for name in names or []` handles None value.
        c = LinkContext("run", load_confidence(), {"Solo": None})
        assert c.canon("solo") == "solo"

    def test_fuse_single_edge_group_passthrough(self):
        # base.py:191-192 -- a correlation group of size 1 passes through as-is.
        c = ctx()
        edge = linker_edge(c, "resolver.compose@1", "CALLS_SERVICE", "s1", "s2",
                           source_label="Service", target_label="Service",
                           confidence=0.95, match_type="topology",
                           evidence=["a:1"])
        fused = fuse_edges([edge])
        assert len(fused) == 1
        assert fused[0] is edge
        assert fused[0].confidence == pytest.approx(0.95)
        assert "+" not in fused[0].detected_by

    def test_load_aliases_missing_file(self):
        # base.py:228-229 -- missing service_aliases.yml returns {}.
        with patch("adduce.services.linker.base.os.path.exists",
                   return_value=False):
            assert load_aliases() == {}

    def test_load_aliases_present_file(self):
        assert isinstance(load_aliases(), dict)

    def test_load_aliases_translates_documented_schema(self, tmp_path):
        # Control-plane schema services:{canonical:{aliases:[...]}} is
        # translated to {canonical: [aliases...]}; empty specs allowed.
        cfg = tmp_path / "service_aliases.yml"
        cfg.write_text(
            "services:\n"
            "  payments:\n"
            "    aliases: [pay-svc, payment]\n"
            "  empty-svc:\n",
            encoding="utf-8")
        with patch("adduce.services.linker.base.config_dir", return_value=str(tmp_path)):
            aliases = load_aliases()
        assert aliases == {"payments": ["pay-svc", "payment"],
                           "empty-svc": []}

    def test_fuse_multi_edge_group_noisy_or(self):
        # base.py:193-216 -- two edges in the same (src,type,tgt) group from
        # different correlation classes: noisy-OR fusion, capped.
        c = ctx()
        e1 = linker_edge(c, "resolver.compose@1", "CALLS_SERVICE", "s1", "s2",
                         source_label="Service", target_label="Service",
                         confidence=0.95, match_type="topology",
                         evidence=["a:1"], extra={"via": ["compose_depends_on"]})
        e2 = linker_edge(c, "rollup.calls@1", "CALLS_SERVICE", "s1", "s2",
                         source_label="Service", target_label="Service",
                         confidence=0.85, match_type="rollup",
                         evidence=["b:2"], extra={"via": ["http"]})
        fused = fuse_edges([e1, e2], cap=0.99)
        assert len(fused) == 1
        assert fused[0].confidence == pytest.approx(min(0.99, 1 - 0.05 * 0.15))
        assert "+" in fused[0].detected_by
        assert fused[0].extra_props["min_confidence"] == pytest.approx(0.85)
        assert fused[0].extra_props["max_confidence"] == fused[0].confidence
        assert sorted(fused[0].extra_props["via"]) == [
            "compose_depends_on", "http"]


# --------------------------------------------------------------------------
# r0_alias.py
# --------------------------------------------------------------------------
class TestR0:
    def test_first_evidence_returns_empty_when_no_evidence(self):
        # r0_alias.py:147 -- _first_evidence returns [] when every claim in the
        # cluster has empty evidence. Two provider claims sharing a repo unify;
        # empty evidence flows through to the HAS_ALIAS edge.
        c = ctx()
        claims = [
            claim("svcname", "provides", "repo_x:payments", repo="repo_x",
                  attrs={"source": "compose", "build_context": "./p"},
                  evidence=[]),
            claim("svcname", "provides", "discovery:payments", repo="repo_x",
                  attrs={"source": "spring.application.name"}, evidence=[]),
        ]
        out = r0_alias.resolve(ClaimIndex(claims), c)
        has_alias = [e for e in out.edges if e.type == "HAS_ALIAS"]
        assert has_alias, "expected HAS_ALIAS edges to be minted"
        assert all(e.evidence == [] for e in has_alias)

    def test_generic_name_multi_scope_splits(self):
        # r0_alias.py:87-88 -- a generic name provided in >1 scope never
        # unifies; each scope gets its own scope-qualified Service id
        # (also hits _service_identity:111-113 qualified branch).
        c = ctx()
        claims = [
            claim("svcname", "provides", "repo_a:api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./api"}),
            claim("svcname", "provides", "repo_b:api", repo="repo_b",
                  attrs={"source": "compose", "build_context": "./api"}),
        ]
        out = r0_alias.resolve(ClaimIndex(claims), c)
        ids = sorted(s.service_id for s in out.services)
        assert ids == ["global:Service:repo_a/api", "global:Service:repo_b/api"]

    def test_built_from_skips_unqualified_source(self):
        # r0_alias.py:126-127 -- a provider whose source is neither
        # spring.application.name nor compose+build_context yields NO
        # BUILT_FROM edge (the `else: continue`).
        c = ctx()
        claims = [
            claim("svcname", "provides", "discovery:orders", repo="repo_o",
                  attrs={"source": "config-filename"},
                  evidence=["orders.yml:1"]),
        ]
        out = r0_alias.resolve(ClaimIndex(claims), c)
        assert [e for e in out.edges if e.type == "BUILT_FROM"] == []
        # Service still minted, just no build provenance edge.
        assert [s.service_id for s in out.services] == ["global:Service:orders"]

    def test_cross_scope_unifies_with_shared_repo(self):
        # r0_alias.py:98-105 -- non-generic name in two scopes that share a
        # repo unify into a single Service (union-find path).
        c = ctx()
        claims = [
            app_name("payments", "repo_x"),
            claim("svcname", "provides", "repo_x:payments", repo="repo_x",
                  attrs={"source": "compose", "build_context": "./p"}),
        ]
        out = r0_alias.resolve(ClaimIndex(claims), c)
        assert [s.service_id for s in out.services] == ["global:Service:payments"]


# --------------------------------------------------------------------------
# r1_compose.py
# --------------------------------------------------------------------------
class TestR1:
    def test_depends_on_becomes_calls_service(self):
        # r1_compose.py:34-46 -- full happy path: provider+consumer within a
        # compose scope emit one CALLS_SERVICE edge with via/confidence.
        c = ctx()
        index = ClaimIndex([
            claim("svcname", "provides", "repo_a:web", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./web"}),
            claim("svcname", "provides", "repo_a:db-api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./db"}),
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="db-api", hint_source="config",
                  attrs={"via": "depends_on", "from": "web"}),
        ])
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        calls = [e for e in out.edges if e.type == "CALLS_SERVICE"]
        assert len(calls) == 1
        assert calls[0].source_id == "global:Service:repo_a/web"
        assert calls[0].target_id == "global:Service:db-api"
        assert calls[0].extra_props["via"] == ["compose_depends_on"]
        assert c.counters["r1.calls_service"] == 1

    def test_env_host_tier(self):
        # r1_compose.py:34-35 -- via == "env_host" selects the env_host tier.
        c = ctx()
        index = ClaimIndex([
            claim("svcname", "provides", "repo_a:web", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./web"}),
            claim("svcname", "provides", "repo_a:db-api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./db"}),
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="db-api", hint_source="config",
                  attrs={"via": "env_host", "from": "web"}),
        ])
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        calls = [e for e in out.edges if e.type == "CALLS_SERVICE"]
        assert len(calls) == 1
        assert calls[0].extra_props["via"] == ["compose_env_host"]

    def test_discovery_scope_skipped(self):
        # r1_compose.py:13-14 -- discovery-scoped consumers are left to R7.
        c = ctx()
        index = ClaimIndex([
            app_name("customers-service", "repo_ms"),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service",
                  hint_source="discovery", attrs={"from": "api-gateway"}),
        ])
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        assert out.edges == []

    def test_no_consumer_identity_counted(self):
        # r1_compose.py:16-18 -- consumer without a 'from' identity is counted.
        c = ctx()
        index = ClaimIndex([
            claim("svcname", "provides", "repo_a:db-api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./db"}),
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="db-api", hint_source="config",
                  attrs={"via": "depends_on"}),
        ])
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        assert out.edges == []
        assert c.counters["r1.no_consumer_identity"] == 1

    def test_unmatched_when_no_provider(self):
        # r1_compose.py:24-26 -- key exists but only as a consumer (no provider).
        c = ctx()
        index = ClaimIndex([
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="web", hint_source="config",
                  attrs={"via": "depends_on", "from": "web"}),
            # another consumer sharing the same key so for_key() is non-empty
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="web2", hint_source="config",
                  attrs={"via": "depends_on", "from": "web2"}),
        ])
        out = r1_compose.resolve(index, c)
        assert out.edges == []
        assert c.counters["r1.unmatched"] == 2

    def test_skip_when_endpoints_missing_or_identical(self):
        # r1_compose.py:31-32 -- source endpoint unresolvable -> skip (no edge,
        # no calls_service counter). Provider exists so we pass the earlier
        # guards, but the consumer 'from' name has no Service/ServiceName.
        c = ctx()
        index = ClaimIndex([
            claim("svcname", "provides", "repo_a:db-api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./db"}),
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="db-api", hint_source="config",
                  attrs={"via": "depends_on", "from": "ghost-consumer"}),
        ])
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        assert [e for e in out.edges if e.type == "CALLS_SERVICE"] == []
        assert c.counters["r1.calls_service"] == 0

    def test_endpoint_falls_back_to_servicename(self):
        # r1_compose.py:54-55 -- _endpoint returns ("ServiceName", sn_id) when
        # a Service was never minted but a ServiceName rendezvous exists.
        c = ctx()
        c.servicename_id[("scope1", "web")] = "global:SvcName:scope1:web"
        assert r1_compose._endpoint(c, "scope1", "web") == (
            "ServiceName", "global:SvcName:scope1:web")

    def test_endpoint_returns_none(self):
        # r1_compose.py:56-57 -- neither Service nor ServiceName known.
        c = ctx()
        assert r1_compose._endpoint(c, "scope1", "nothing") is None


# --------------------------------------------------------------------------
# r4_gateway.py
# --------------------------------------------------------------------------
class TestR4:
    def test_route_becomes_routes_to(self):
        # r4_gateway.py:53-67 -- minted gateway + minted target -> ROUTES_TO
        # edge and a gateway ServiceSpec.
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_ms",
                     module="spring-petclinic-api-gateway"),
            app_name("customers-service", "repo_ms",
                     module="spring-petclinic-customers-service"),
            claim("route", "consumes",
                  "/api/customer/**\u2192svcname:customers-service",
                  repo="repo_ms", hint="api-gateway", hint_source="config",
                  attrs={"target": "customers-service",
                         "path_prefix": "/api/customer", "strip_prefix": 2},
                  evidence=["spring-petclinic-api-gateway/src/main/resources/"
                            "application.yml:30"]),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service",
                  hint_source="discovery"),
        ])
        r0_alias.resolve(index, c)
        out = r4_gateway.resolve(index, c)
        routes = [e for e in out.edges if e.type == "ROUTES_TO"]
        assert len(routes) == 1
        assert routes[0].source_id == "global:Service:api-gateway"
        assert routes[0].target_id == "global:Service:customers-service"
        assert routes[0].extra_props["strip_path"] == 2
        assert c.counters["r4.routes"] == 1
        gateways = [s for s in out.services if s.is_gateway]
        assert [g.service_id for g in gateways] == ["global:Service:api-gateway"]

    def test_dead_end_servicename_target_counted(self):
        # r4_gateway.py:38-39 -- target resolves to a discovery ServiceName
        # (not a minted Service) -> dead_end_targets counted, ROUTES_TO still
        # emitted from the gateway to the ServiceName dead-end.
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_ms"),
            claim("route", "consumes",
                  "/api/vets/**\u2192svcname:vets-service", repo="repo_ms",
                  hint="api-gateway", hint_source="config",
                  attrs={"target": "vets-service", "path_prefix": "/api/vets",
                         "strip_prefix": 2}),
            claim("svcname", "consumes", "discovery:vets-service",
                  repo="repo_ms", hint="vets-service", hint_source="discovery"),
        ])
        r0_alias.resolve(index, c)
        out = r4_gateway.resolve(index, c)
        routes = [e for e in out.edges if e.type == "ROUTES_TO"]
        assert routes[0].target_id == "global:SvcName:discovery:vets-service"
        assert routes[0].target_label == "ServiceName"
        assert c.counters["r4.dead_end_targets"] == 1

    def test_no_target_is_counted(self):
        # r4_gateway.py:19-21 -- route claim with no target name.
        c = ctx()
        index = ClaimIndex([
            claim("route", "consumes", "/api/**\u2192svcname:", repo="repo_ms",
                  hint="api-gateway", hint_source="config",
                  attrs={"path_prefix": "/api"}),
        ])
        out = r4_gateway.resolve(index, c)
        assert out.edges == []
        assert c.counters["r4.no_target"] == 1

    def test_dead_end_no_servicename(self):
        # r4_gateway.py:34-37 -- target resolves to neither Service nor a
        # discovery ServiceName -> dead end, counted, no edge for this claim.
        c = ctx()
        index = ClaimIndex([
            claim("route", "consumes",
                  "/api/vets/**\u2192svcname:vets-service", repo="repo_ms",
                  hint="api-gateway", hint_source="config",
                  attrs={"target": "vets-service", "path_prefix": "/api/vets",
                         "strip_prefix": 2}),
        ])
        # No r0 pass -> no ServiceName minted for vets-service.
        out = r4_gateway.resolve(index, c)
        assert out.edges == []
        assert c.counters["r4.dead_end_no_servicename"] == 1

    def test_gateway_unminted_still_emits_resolved_to(self):
        # r4_gateway.py:50-52 -- gateway service was never minted: RESOLVED_TO
        # still emitted (dead-end honesty), but ROUTES_TO is skipped/counted.
        c = ctx()
        index = ClaimIndex([
            app_name("customers-service", "repo_ms",
                     module="customers-service"),
            claim("route", "consumes",
                  "/api/customer/**\u2192svcname:customers-service",
                  repo="repo_ms", hint="api-gateway", hint_source="config",
                  attrs={"target": "customers-service",
                         "path_prefix": "/api/customer", "strip_prefix": 2}),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service",
                  hint_source="discovery"),
        ])
        r0_alias.resolve(index, c)
        out = r4_gateway.resolve(index, c)
        # api-gateway service never minted -> no ROUTES_TO, counter bumped.
        assert [e for e in out.edges if e.type == "ROUTES_TO"] == []
        assert c.counters["r4.gateway_unminted"] == 1
        resolved = [e for e in out.edges if e.type == "RESOLVED_TO"]
        assert len(resolved) == 1
        # RESOLVED_TO prefers the discovery ServiceName rendezvous id.
        assert resolved[0].target_id == "global:SvcName:discovery:customers-service"

    def test_target_endpoint_returns_none(self):
        # r4_gateway.py:82 -- _target_endpoint returns None for unknown name.
        c = ctx()
        assert r4_gateway._target_endpoint(c, "nobody") is None

    def test_target_endpoint_service_and_servicename(self):
        # r4_gateway.py:76-81 -- Service tier then discovery ServiceName tier.
        c = ctx()
        c.service_by_name["known-svc"] = "global:Service:known-svc"
        assert r4_gateway._target_endpoint(c, "known-svc") == (
            "Service", "global:Service:known-svc")
        c.servicename_id[("discovery", "sn-only")] = "global:SvcName:discovery:sn-only"
        assert r4_gateway._target_endpoint(c, "sn-only") == (
            "ServiceName", "global:SvcName:discovery:sn-only")


# --------------------------------------------------------------------------
# r7_http.py
# --------------------------------------------------------------------------
class TestR7:
    def _run(self, claims):
        c = ctx()
        index = ClaimIndex(claims)
        r0_alias.resolve(index, c)
        r4_gateway.resolve(index, c)
        c.normalized_calls = normalize_http_calls(index, c)
        out = r7_http.resolve(index, c)
        return c, out

    def test_hint_template_and_exact_and_invokes(self):
        # r7_http.py happy path -- INVOKES + RESOLVED_TO emitted, tier chosen.
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", "customers-service"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].match_type == "hint_exact"
        assert invokes[0].confidence == pytest.approx(0.95)
        assert c.counters["r7.invokes"] == 1

    def test_unqualified_hint_counted(self):
        # r7_http.py:37-39 -- consumer with unqualified hint source is skipped.
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", None, source="none"),
        ])
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.unqualified"] == 1

    def test_unmatched_qualified_counted(self):
        # r7_http.py:47-49 -- qualified hint but no provider in that scope.
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", "billing-service"),
        ])
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.unmatched_qualified"] == 1

    def test_gateway_rewrite_reaches_backend(self):
        # r7_http.py:142-147 -- gateway rewrite table strips the prefix and
        # rewrites the hint to the backend service, then matches its contract.
        c, out = self._run([
            app_name("api-gateway", "repo_ms", module="api-gateway"),
            app_name("customers-service", "repo_ms", module="customers-service"),
            claim("route", "consumes",
                  "/api/customer/**\u2192svcname:customers-service",
                  repo="repo_ms", hint="api-gateway", hint_source="config",
                  attrs={"target": "customers-service",
                         "path_prefix": "/api/customer", "strip_prefix": 2}),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service",
                  hint_source="discovery"),
            _provider("/owners/{}", repo="repo_ms", module="customers-service"),
            _consumer("/api/customer/owners/{}", "api-gateway", repo="repo_web"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].target_id == "global:Http:customers-service:GET:/owners/{}"
        assert "gateway_rewrite" in invokes[0].extra_props["via"]
        assert c.counters["r7.gateway_rewrites"] == 1

    def test_non_httpcall_consumer_skipped(self):
        # r7_http.py:34-35 -- consumer key not starting with "httpcall:".
        c = ctx()
        index = ClaimIndex([
            claim("http", "consumes", "weird:GET:/owners/{}", repo="repo_cons",
                  hint="customers-service", hint_source="discovery"),
        ])
        c.normalized_calls = normalize_http_calls(index, c)
        out = r7_http.resolve(index, c)
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.unqualified"] == 0

    def test_hint_differs_from_own_scope_still_matches(self):
        # r7_http.py -- single cross-repo provider: intra-repo narrowing finds
        # no same-repo provider, so the hint-matched provider is used
        # unchanged and no precedence counter fires.
        c = ctx()
        index = ClaimIndex([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}", repo="repo_prov",
                      module="customers-service"),
        ])
        r0_alias.resolve(index, c)
        r4_gateway.resolve(index, c)
        # consumer in a repo whose own scope is just the repo id ("repo_web"),
        # which differs from the hint "customers-service".
        consumer = claim(
            "http", "consumes", "httpcall:GET:/owners/{}", repo="repo_web",
            hint="customers-service", hint_source="discovery",
            evidence=["repo_web/src/main/java/Client.java:12"],
            enode="repo_web:file:Client.java", etype="File")
        index2 = ClaimIndex(index.claims + [consumer])
        c.normalized_calls = normalize_http_calls(index2, c)
        out = r7_http.resolve(index2, c)
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert c.counters.get("r7.intra_precedence", 0) == 0
        assert invokes[0].target_repo_id == "repo_prov"

    def test_intra_repo_precedence_prefers_same_repo_provider(self):
        # r7_http.py -- when the hinted scope has matching providers from
        # multiple repos, providers in the consumer's own repo win.
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}", repo="repo_prov",
                      module="customers-service"),
            app_name("customers-service", "repo_cons",
                     module="embedded-customers"),
            _provider("/owners/{id}", repo="repo_cons",
                      module="embedded-customers"),
            _consumer("/owners/{}", "customers-service", repo="repo_cons"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].target_id == (
            "global:Http:customers-service:GET:/owners/{id}")
        assert invokes[0].match_type == "hint_template"
        assert invokes[0].target_repo_id == "repo_cons"
        assert c.counters["r7.intra_precedence"] == 1

    def test_duplicate_contract_deduped(self):
        # r7_http.py:59-61 -- two providers sharing the same contract_id: the
        # second is skipped via the `seen` set (only one INVOKES edge).
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}", repo="repo_prov",
                      module="customers-service"),
            # second provider, same scope+method+template => same contract_id
            claim("http", "provides", "GET:/owners/{}", repo="repo_prov",
                  evidence=["customers-service/src/main/java/Other.java:5"],
                  enode="repo_prov:endpoint:GET:/owners/{}b",
                  etype="ApiEndpoint"),
            _consumer("/owners/{}", "customers-service", repo="repo_cons"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1

    def test_no_call_site_node_skipped(self):
        # r7_http.py:67-69 -- matched provider but consumer has no evidence
        # node id -> no INVOKES, counter bumped, no r7.invokes.
        c, out = self._run([
            app_name("customers-service", "repo_prov",
                     module="customers-service"),
            _provider("/owners/{}", repo="repo_prov",
                      module="customers-service"),
            # consumer with evidence_node_id explicitly None (no call-site node)
            claim("http", "consumes", "httpcall:GET:/owners/{}",
                  repo="repo_cons", hint="customers-service",
                  hint_source="discovery",
                  evidence=["repo_cons/src/main/java/Client.java:12"],
                  enode=None, etype="File"),
        ])
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.no_call_site_node"] == 1
        assert c.counters["r7.invokes"] == 0

    def test_rewrite_no_matching_prefix(self):
        # path_algebra.resolve_chain -- rewrite rules exist for the hint but
        # none of their prefixes match the template -> zero hops, unchanged.
        from adduce.services.linker.base import RouteRule
        from adduce.services.linker.path_algebra import resolve_chain

        c = ctx()
        c.rewrite_routes["api-gateway"] = [
            RouteRule(prefix="/api/other", strip_prefix=1, rewrite_pattern="",
                      rewrite_replacement="", target_name="other-service",
                      evidence=[]),
        ]
        chain = resolve_chain(c, "api-gateway", "/api/customer/owners/{}")
        assert (chain.service, chain.template, chain.hops) == \
            ("api-gateway", "/api/customer/owners/{}", 0)
        assert c.counters["r7.gateway_rewrites"] == 0


# --------------------------------------------------------------------------
# rollups.py
# --------------------------------------------------------------------------
class TestRollups:
    def _invoke(self, ctxobj, source_repo, target_repo, target_id, evidence,
                source_id="node:client", confidence=0.85):
        return linker_edge(
            ctxobj, "resolver.http@1", "INVOKES", source_id, target_id,
            source_label="GraphNode", target_label="HttpContract",
            confidence=confidence, match_type="hint_template",
            evidence=evidence, source_repo=source_repo,
            target_repo=target_repo, extra={"via": ["http"]})

    def test_rollup_calls_service_happy_path(self):
        # rollups.py:52-73 -- an INVOKES that maps both ends to distinct
        # Services yields a CALLS_SERVICE rollup with weight/via/edge ids.
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_a", module="gw"),
            app_name("customers-service", "repo_b", module="cust"),
        ])
        r0_alias.resolve(index, c)
        invoke = linker_edge(
            c, "resolver.http@1", "INVOKES", "repo_a:file:Client.java",
            "global:Http:customers-service:GET:/owners/{}",
            source_label="GraphNode", target_label="HttpContract",
            confidence=0.85, match_type="hint_template",
            evidence=["gw/src/main/java/Client.java:12"],
            source_repo="repo_a", target_repo="repo_b", extra={"via": ["http"]})
        rollups = build_rollups(c, [invoke], "2026-07-26T00:00:00Z")
        calls = [e for e in rollups if e.type == "CALLS_SERVICE"]
        deps = [e for e in rollups if e.type == "DEPENDS_ON_REPO"]
        assert len(calls) == 1
        assert calls[0].source_id == "global:Service:api-gateway"
        assert calls[0].target_id == "global:Service:customers-service"
        assert calls[0].extra_props["weight"] == 1
        assert calls[0].extra_props["evidence_edge_ids"] == [
            "repo_a:file:Client.java|INVOKES|"
            "global:Http:customers-service:GET:/owners/{}"]
        assert c.counters["rollup.calls_service"] == 1
        assert len(deps) == 1
        assert deps[0].source_id == "repo_a" and deps[0].target_id == "repo_b"
        assert deps[0].extra_props["via"] == ["http"]

    def test_consumer_service_none_no_module(self):
        # rollups.py:24-26 -- module_service_name is None (no module registered)
        # -> _consumer_service returns None -> calls_unmapped counted, no rollup.
        c = ctx()
        edge = self._invoke(
            c, "repo_a", "repo_b",
            "global:Http:customers-service:GET:/owners/{}",
            ["gw/src/main/java/Client.java:12"])
        rollups = build_rollups(c, [edge], "2026-07-26T00:00:00Z")
        assert [e for e in rollups if e.type == "CALLS_SERVICE"] == []
        assert c.counters["rollup.calls_unmapped"] == 1

    def test_contract_service_short_id(self):
        # rollups.py:31-33 -- contract id with fewer than 5 colon-parts.
        c = ctx()
        assert r0_alias  # sanity import
        from adduce.services.linker import rollups as R
        assert R._contract_service(c, "global:Http:only") is None

    def test_calls_unmapped_when_contract_unmapped(self):
        # rollups.py:45-48 -- consumer maps to a Service but the contract scope
        # does not map to any Service -> calls_unmapped, no rollup edge.
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_a", module="gw"),
        ])
        r0_alias.resolve(index, c)
        edge = self._invoke(
            c, "repo_a", "repo_b",
            "global:Http:unknown-scope:GET:/x/{}",
            ["gw/src/main/java/Client.java:12"])
        rollups = build_rollups(c, [edge], "2026-07-26T00:00:00Z")
        assert [e for e in rollups if e.type == "CALLS_SERVICE"] == []
        assert c.counters["rollup.calls_unmapped"] == 1

    def test_calls_intra_skipped(self):
        # rollups.py:49-51 -- source service == target service -> skipped.
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_a", module="gw"),
        ])
        r0_alias.resolve(index, c)
        # both consumer module and contract scope resolve to api-gateway.
        edge = self._invoke(
            c, "repo_a", "repo_a",
            "global:Http:api-gateway:GET:/x/{}",
            ["gw/src/main/java/Client.java:12"])
        rollups = build_rollups(c, [edge], "2026-07-26T00:00:00Z")
        assert [e for e in rollups if e.type == "CALLS_SERVICE"] == []
        assert c.counters["rollup.calls_intra_skipped"] == 1

    def test_depends_on_add_skips_self_repo(self):
        # rollups.py:84-85 -- add() early-returns when source_repo == target
        # repo. A ROUTES_TO whose gateway and target service map to the SAME
        # repo drives add() with equal repos (line 85 return); a separate
        # cross-repo pairing still yields exactly one DEPENDS_ON_REPO edge.
        c = ctx()
        # gateway and target both resolve to repo_same -> add() returns at 85.
        c.service_repos["global:Service:gw"] = {"repo_same"}
        c.service_repos["global:Service:tgt"] = {"repo_same"}
        selfroute = linker_edge(
            c, "resolver.gateway@1", "ROUTES_TO", "global:Service:gw",
            "global:Service:tgt", source_label="Service",
            target_label="Service", confidence=0.98, match_type="declared",
            evidence=["r:1"])
        cross = self._invoke(
            c, "repo_a", "repo_b",
            "global:Http:customers-service:GET:/owners/{}",
            ["gw/src/main/java/Client.java:12"])
        rollups = build_rollups(c, [selfroute, cross], "2026-07-26T00:00:00Z")
        deps = [e for e in rollups if e.type == "DEPENDS_ON_REPO"]
        # only the cross-repo INVOKES survives; the self-repo route is dropped.
        assert len(deps) == 1
        assert deps[0].source_id == "repo_a" and deps[0].target_id == "repo_b"

    def test_depends_on_from_calls_service_and_routes_to(self):
        # rollups.py:96-102 -- CALLS_SERVICE cross_repo branch and ROUTES_TO
        # branch (expanded through service_repos) both feed DEPENDS_ON_REPO.
        c = ctx()
        c.service_repos["global:Service:gw"] = {"repo_gw"}
        c.service_repos["global:Service:cust"] = {"repo_cust"}
        calls = linker_edge(
            c, "resolver.compose@1", "CALLS_SERVICE", "global:Service:a",
            "global:Service:b", source_label="Service", target_label="Service",
            confidence=0.9, match_type="topology", evidence=["e:1"],
            source_repo="repo_x", target_repo="repo_y",
            extra={"via": ["compose"]})
        assert calls.cross_repo is True
        routes = linker_edge(
            c, "resolver.gateway@1", "ROUTES_TO", "global:Service:gw",
            "global:Service:cust", source_label="Service",
            target_label="Service", confidence=0.98, match_type="declared",
            evidence=["r:1"], source_repo="repo_gw", target_repo="repo_cust")
        rollups = build_rollups(c, [calls, routes], "2026-07-26T00:00:00Z")
        deps = {(e.source_id, e.target_id): e for e in rollups
                if e.type == "DEPENDS_ON_REPO"}
        # from CALLS_SERVICE: repo_x -> repo_y via "compose"
        assert ("repo_x", "repo_y") in deps
        assert deps[("repo_x", "repo_y")].extra_props["via"] == ["compose"]
        # from ROUTES_TO expansion: repo_gw -> repo_cust via "route"
        assert ("repo_gw", "repo_cust") in deps
        assert deps[("repo_gw", "repo_cust")].extra_props["via"] == ["route"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
