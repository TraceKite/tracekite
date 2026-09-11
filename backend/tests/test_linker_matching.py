import pytest
from unittest.mock import patch

from evigraph.services.linker.normalize import normalize_http_calls
from evigraph.services.linker import r0_alias, r4_gateway, r7_http
from evigraph.services.linker.base import (
    ClaimIndex, ClaimRecord, LinkContext, fuse_edges, linker_edge,
    load_aliases, load_confidence, positional,
)
from evigraph.services.linker.rollups import build_rollups


def claim(kind, direction, key, repo="repo_a", hint=None, hint_source="none",
          matchable=True, attrs=None, evidence=None, enode=None, etype=""):
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=matchable, attrs=attrs or {},
        evidence=evidence or [f"{repo}/src/App.java:10"],
        evidence_node_id=enode, evidence_node_type=etype,
    )


def app_name(name, repo, module=None):
    path = f"{module or name}/src/main/resources/application.yml:2"
    return claim("svcname", "provides", f"discovery:{name}", repo=repo,
                 attrs={"source": "spring.application.name"}, evidence=[path])


def ctx():
    return LinkContext("linkrun_test", load_confidence(), {})


def _provider(template, repo="repo_prov", module="customers-service"):
    return claim("http", "provides", f"GET:{template}", repo=repo,
                 evidence=[f"{module}/src/main/java/OwnerResource.java:40"],
                 enode=f"{repo}:endpoint:GET:{template}", etype="ApiEndpoint")


def _consumer(template, hint, repo="repo_cons", source="discovery"):
    return claim("http", "consumes", f"httpcall:GET:{template}", repo=repo,
                 hint=hint, hint_source=source,
                 evidence=[f"{repo}/src/main/java/Client.java:12"],
                 enode=f"{repo}:file:Client.java", etype="File")


class TestR7:
    def _run(self, claims):
        c = ctx()
        index = ClaimIndex(claims)
        r0_alias.resolve(index, c)
        r4_gateway.resolve(index, c)
        c.normalized_calls = normalize_http_calls(index, c)
        out = r7_http.resolve(index, c)
        return c, out

    def test_hint_template_match_tiers(self):
        c, out = self._run([
            app_name("customers-service", "repo_prov", module="customers-service"),
            _provider("/owners/{ownerId}"),
            _consumer("/owners/{}", "customers-service"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].confidence == pytest.approx(0.85)
        assert invokes[0].match_type == "hint_template"
        assert invokes[0].cross_repo is True

        c2, out2 = self._run([
            app_name("customers-service", "repo_prov", module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", "customers-service"),
        ])
        invokes2 = [e for e in out2.edges if e.type == "INVOKES"]
        assert invokes2[0].confidence == pytest.approx(0.95)
        assert invokes2[0].match_type == "hint_exact"

    def test_unqualified_hints_are_excluded(self):
        c, out = self._run([
            app_name("customers-service", "repo_prov", module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", None, source="none"),
            _consumer("/owners/{}", "localhost", source="local"),
        ])
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.unqualified"] == 2

    def test_wrong_hint_no_match_is_honest(self):
        c, out = self._run([
            app_name("customers-service", "repo_prov", module="customers-service"),
            _provider("/owners/{}"),
            _consumer("/owners/{}", "billing-service"),
        ])
        assert [e for e in out.edges if e.type == "INVOKES"] == []
        assert c.counters["r7.unmatched_qualified"] == 1

    def test_gateway_rewrite_reaches_backend(self):
        c, out = self._run([
            app_name("api-gateway", "repo_ms", module="api-gateway"),
            app_name("customers-service", "repo_ms", module="customers-service"),
            claim("route", "consumes", "/api/customer/**→svcname:customers-service",
                  repo="repo_ms", hint="api-gateway", hint_source="config",
                  attrs={"target": "customers-service",
                         "path_prefix": "/api/customer", "strip_prefix": 2}),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service", hint_source="discovery"),
            _provider("/owners/{}", repo="repo_ms", module="customers-service"),
            _consumer("/api/customer/owners/{}", "api-gateway", repo="repo_web"),
        ])
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].target_id == "global:Http:customers-service:GET:/owners/{}"
        assert "gateway_rewrite" in invokes[0].extra_props["via"]
        assert c.counters["r7.gateway_rewrites"] == 1

    def test_exposes_emitted_per_endpoint(self):
        c, out = self._run([
            app_name("customers-service", "repo_prov", module="customers-service"),
            _provider("/owners/{}"),
        ])
        exposes = [e for e in out.edges if e.type == "EXPOSES"]
        assert len(exposes) == 1
        assert exposes[0].source_id == "repo_prov:endpoint:GET:/owners/{}"
        contracts = [r for r in out.rendezvous if r.label == "HttpContract"]
        assert contracts[0].props["service_scope"] == "customers-service"


class TestFusionAndRollups:
    def test_fusion_noisy_or_across_groups(self):
        c = ctx()
        e1 = linker_edge(c, "resolver.compose@1", "CALLS_SERVICE", "s1", "s2",
                         source_label="Service", target_label="Service",
                         confidence=0.95, match_type="topology", evidence=["a:1"],
                         extra={"via": ["compose_depends_on"]})
        e2 = linker_edge(c, "rollup.calls@1", "CALLS_SERVICE", "s1", "s2",
                         source_label="Service", target_label="Service",
                         confidence=0.85, match_type="rollup", evidence=["b:2"],
                         extra={"via": ["http"]})
        fused = fuse_edges([e1, e2], cap=0.99)
        assert len(fused) == 1
        assert fused[0].confidence == pytest.approx(min(0.99, 1 - 0.05 * 0.15))
        assert "+" in fused[0].detected_by
        assert fused[0].extra_props["min_confidence"] == pytest.approx(0.85)
        assert sorted(fused[0].extra_props["via"]) == ["compose_depends_on", "http"]

    def test_rollup_calls_service_and_depends_on_repo(self):
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
            source_repo="repo_a", target_repo="repo_b",
            extra={"via": ["http"]})
        rollups = build_rollups(c, [invoke], "2026-07-26T00:00:00Z")
        calls = [e for e in rollups if e.type == "CALLS_SERVICE"]
        deps = [e for e in rollups if e.type == "DEPENDS_ON_REPO"]
        assert len(calls) == 1
        assert calls[0].source_id == "global:Service:api-gateway"
        assert calls[0].target_id == "global:Service:customers-service"
        assert calls[0].extra_props["weight"] == 1
        assert calls[0].extra_props["evidence_edge_ids"] == [
            "repo_a:file:Client.java|INVOKES|global:Http:customers-service:GET:/owners/{}"]
        assert len(deps) == 1
        assert deps[0].source_id == "repo_a" and deps[0].target_id == "repo_b"
        assert deps[0].extra_props["via"] == ["http"]

    def test_positional_and_config_loaders(self):
        assert positional("/owners/{ownerId}/pets/{petId}") == "/owners/{}/pets/{}"
        conf = load_confidence()
        assert conf["floor"] == 0.6
        assert isinstance(load_aliases(), dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_health_everywhere_needs_hint_agreement():
    c = LinkContext("linkrun_test", load_confidence(), {})
    index = ClaimIndex([
        app_name("customers-service", "repo_a", module="cust"),
        app_name("vets-service", "repo_b", module="vets"),
        _provider("/health", repo="repo_a", module="cust"),
        _provider("/health", repo="repo_b", module="vets"),
        _consumer("/health", "vets-service", repo="repo_c"),
        _consumer("/health", None, repo="repo_d", source="none"),
    ])
    r0_alias.resolve(index, c)
    c.normalized_calls = normalize_http_calls(index, c)
    out = r7_http.resolve(index, c)
    invokes = [e for e in out.edges if e.type == "INVOKES"]
    assert len(invokes) == 1
    assert invokes[0].target_id == "global:Http:vets-service:GET:/health"
    assert c.counters["r7.unqualified"] == 1


class TestFusionPreservesEvidence:
    """Regression: fusion inherited only the highest-confidence contributor's
    extra_props, so a corroborated Layer-2 rollup lost evidence_edge_ids and the
    zoom-down invariant (design §5.3) broke on the best edges."""

    @staticmethod
    def _pair():
        c = LinkContext("linkrun_test", load_confidence(), {})
        rollup = linker_edge(
            c, "rollup.calls@1", "CALLS_SERVICE", "global:Service:web",
            "global:Service:orders", source_label="Service",
            target_label="Service", confidence=0.85, match_type="rollup",
            evidence=["web/src/client.java:9"], origin="inferred",
            source_repo="repo_web", target_repo="repo_orders",
            extra={"weight": 3, "via": ["http"],
                   "evidence_edge_ids": ["n1|INVOKES|global:Http:orders:GET:/x"],
                   "derived_by": "rollup.calls@1", "resolved_at": "T"})
        topo = linker_edge(
            c, "resolver.compose@1", "CALLS_SERVICE", "global:Service:web",
            "global:Service:orders", source_label="Service",
            target_label="Service", confidence=0.96, match_type="topology",
            evidence=["repo_web/docker-compose.yml:4"], origin="matched",
            extra={"via": ["compose_depends_on"]})
        return c, rollup, topo

    def test_evidence_edge_ids_survive_fusion(self):
        _, rollup, topo = self._pair()
        fused = fuse_edges([topo, rollup], 0.99)
        assert len(fused) == 1
        props = fused[0].extra_props
        assert props["evidence_edge_ids"] == [
            "n1|INVOKES|global:Http:orders:GET:/x"]
        assert props["derived_by"] == "rollup.calls@1"
        assert props["resolved_at"] == "T"
        assert props["weight"] == 3

    def test_via_unions_and_confidence_noisy_ors(self):
        _, rollup, topo = self._pair()
        fused = fuse_edges([topo, rollup], 0.99)[0]
        assert fused.extra_props["via"] == ["compose_depends_on", "http"]
        # independent groups (topology vs http) noisy-OR above either input
        assert fused.confidence > 0.96
        assert fused.confidence <= 0.99
        assert fused.extra_props["max_confidence"] == fused.confidence
        assert fused.extra_props["min_confidence"] == pytest.approx(0.85)

    def test_repo_attribution_survives_from_any_contributor(self):
        _, rollup, topo = self._pair()
        fused = fuse_edges([topo, rollup], 0.99)[0]
        assert fused.source_repo_id == "repo_web"
        assert fused.target_repo_id == "repo_orders"
        assert fused.cross_repo is True

    def test_correlated_resolvers_do_not_inflate(self):
        # Two topology-group edges are correlated: max, never noisy-OR.
        c = LinkContext("linkrun_test", load_confidence(), {})
        kw = dict(source_label="Service", target_label="Service",
                  match_type="topology", evidence=["a:1"])
        compose = linker_edge(c, "resolver.compose@1", "CALLS_SERVICE",
                              "s:a", "s:b", confidence=0.96, **kw)
        k8s = linker_edge(c, "resolver.k8s@1", "CALLS_SERVICE",
                          "s:a", "s:b", confidence=0.9, **kw)
        fused = fuse_edges([compose, k8s], 0.99)[0]
        assert fused.confidence == pytest.approx(0.96)

    def test_evidence_edge_ids_capped(self):
        c = LinkContext("linkrun_test", load_confidence(), {})
        kw = dict(source_label="Service", target_label="Service",
                  match_type="rollup", evidence=["a:1"])
        edges = [
            linker_edge(c, f"rollup.calls@{i}", "CALLS_SERVICE", "s:a", "s:b",
                        confidence=0.8, extra={"evidence_edge_ids": [f"e{i}"]},
                        **kw)
            for i in range(15)
        ]
        fused = fuse_edges(edges, 0.99)[0]
        assert len(fused.extra_props["evidence_edge_ids"]) == 10


class TestConfidenceControlPlane:
    """Regression: KG_CONFIG_DIR was not mapped to the settings field, so the
    deployed backend silently fell back to 0.6 for every resolver tier — which
    is exactly the floor, so everything still published as `active`."""

    def test_shipped_table_loads_with_all_landed_tiers(self):
        conf = load_confidence()
        assert conf["floor"] == 0.6
        assert conf["fusion_cap"] == 0.99
        for resolver, tiers in (("r0", ("resolved_to", "has_alias",
                                        "built_from_build_context",
                                        "built_from_app_name",
                                        "built_from_descriptor")),
                                ("r1", ("depends_on", "env_host")),
                                ("r4", ("route_declared",)),
                                ("r7", ("hint_exact", "hint_template",
                                        "exposes"))):
            for tier in tiers:
                assert tier in conf[resolver], f"{resolver}.{tier} missing"
                assert 0.0 < conf[resolver][tier] <= 1.0

    def test_tiers_are_not_all_the_fallback(self):
        # The symptom of the bug: every served confidence collapses to 0.6.
        c = LinkContext("linkrun_test", load_confidence(), {})
        assert c.conf("r4", "route_declared") == pytest.approx(0.98)
        assert c.conf("r1", "depends_on") == pytest.approx(0.96)
        assert c.conf("r7", "hint_exact") == pytest.approx(0.95)

    def test_missing_table_fails_closed(self, tmp_path):
        from evigraph.services.linker.base import ConfidenceTableMissing
        with patch("evigraph.services.linker.base.config_dir",
                   return_value=str(tmp_path)):
            with pytest.raises(ConfidenceTableMissing):
                load_confidence()

    def test_kg_config_dir_env_alias_is_wired(self, monkeypatch, tmp_path):
        from evigraph.config import Settings
        monkeypatch.setenv("KG_CONFIG_DIR", str(tmp_path))
        assert Settings().config_dir == str(tmp_path)
