import pytest

from tracekite.services.linker import r0_alias, r1_compose, r4_gateway
from tracekite.services.linker.normalize import normalize_http_calls
from tracekite.services.linker.base import ClaimIndex, ClaimRecord, LinkContext, load_confidence


def claim(kind, direction, key, repo="repo_a", hint=None, hint_source="none",
          matchable=True, attrs=None, evidence=None, enode=None, etype=""):
    return ClaimRecord(
        id=f"claim:{repo}:{kind}:{direction}:{key}", repo_id=repo, kind=kind,
        direction=direction, key=key, service_hint=hint,
        hint_source=hint_source, matchable=matchable, attrs=attrs or {},
        evidence=evidence or [f"{repo}/src/main/resources/application.yml:1"],
        evidence_node_id=enode, evidence_node_type=etype,
    )


def ctx():
    return LinkContext("linkrun_test", load_confidence(), {})


def app_name(name, repo, module=None):
    path = f"{module or name}/src/main/resources/application.yml:2"
    return claim("svcname", "provides", f"discovery:{name}", repo=repo,
                 attrs={"source": "spring.application.name"}, evidence=[path])


class TestR0:
    def test_config_filename_provider_joins_but_no_built_from(self):
        c = ctx()
        claims = [
            app_name("customers-service", "repo_ms"),
            claim("svcname", "provides", "discovery:customers-service",
                  repo="repo_cfg", attrs={"source": "config-filename"},
                  evidence=["customers-service.yml:1"]),
        ]
        out = r0_alias.resolve(ClaimIndex(claims), c)
        services = [s for s in out.services]
        assert [s.service_id for s in services] == ["global:Service:customers-service"]
        built = [e for e in out.edges if e.type == "BUILT_FROM"]
        assert [e.target_id for e in built] == ["repo_ms"]
        names = [r for r in out.rendezvous if r.label == "ServiceName"]
        assert len(names) == 1
        assert sorted(names[0].props["repo_ids"]) == ["repo_cfg", "repo_ms"]
        resolved = [e for e in out.edges if e.type == "RESOLVED_TO"]
        assert len(resolved) == 2

    def test_generic_names_never_unify_across_scopes(self):
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

    def test_cross_scope_unifies_only_with_shared_repo(self):
        c = ctx()
        shared = [
            app_name("payments", "repo_x"),
            claim("svcname", "provides", "repo_x:payments", repo="repo_x",
                  attrs={"source": "compose", "build_context": "./p"}),
        ]
        out = r0_alias.resolve(ClaimIndex(shared), c)
        assert [s.service_id for s in out.services] == ["global:Service:payments"]

        c2 = ctx()
        unshared = [
            app_name("payments", "repo_x"),
            claim("svcname", "provides", "repo_y:payments", repo="repo_y",
                  attrs={"source": "compose", "build_context": "./p"}),
        ]
        out2 = r0_alias.resolve(ClaimIndex(unshared), c2)
        assert sorted(s.service_id for s in out2.services) == [
            "global:Service:discovery/payments", "global:Service:repo_y/payments"]

    def test_module_registration_for_monorepo_scoping(self):
        c = ctx()
        r0_alias.resolve(ClaimIndex([
            app_name("customers-service", "repo_ms",
                     module="spring-petclinic-customers-service"),
            app_name("api-gateway", "repo_ms",
                     module="spring-petclinic-api-gateway"),
        ]), c)
        path = "spring-petclinic-customers-service/src/main/java/x/OwnerResource.java"
        assert c.scope_for("repo_ms", path) == "customers-service"
        assert c.scope_for("repo_ms", "unknown/path.java") == "repo_ms"


class TestR1:
    def _claims(self):
        return [
            claim("svcname", "provides", "repo_a:web", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./web"}),
            claim("svcname", "provides", "repo_a:db-api", repo="repo_a",
                  attrs={"source": "compose", "build_context": "./db"}),
            claim("svcname", "consumes", "repo_a:db-api", repo="repo_a",
                  hint="db-api", hint_source="config",
                  attrs={"via": "depends_on", "from": "web"}),
        ]

    def test_depends_on_becomes_calls_service(self):
        c = ctx()
        index = ClaimIndex(self._claims())
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        calls = [e for e in out.edges if e.type == "CALLS_SERVICE"]
        assert len(calls) == 1
        assert calls[0].source_id == "global:Service:repo_a/web"
        assert calls[0].target_id == "global:Service:db-api"
        assert calls[0].extra_props["via"] == ["compose_depends_on"]
        assert calls[0].extra_props["min_confidence"] == calls[0].confidence

    def test_missing_consumer_identity_is_counted_not_guessed(self):
        c = ctx()
        claims = self._claims()
        claims[2].attrs.pop("from")
        index = ClaimIndex(claims)
        r0_alias.resolve(index, c)
        out = r1_compose.resolve(index, c)
        assert out.edges == []
        assert c.counters["r1.no_consumer_identity"] == 1

    def test_discovery_scope_left_to_r7(self):
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


class TestR4:
    def _index(self):
        return ClaimIndex([
            app_name("api-gateway", "repo_ms",
                     module="spring-petclinic-api-gateway"),
            app_name("customers-service", "repo_ms",
                     module="spring-petclinic-customers-service"),
            claim("route", "consumes",
                  "/api/customer/**→svcname:customers-service", repo="repo_ms",
                  hint="api-gateway", hint_source="config",
                  attrs={"target": "customers-service",
                         "path_prefix": "/api/customer", "strip_prefix": 2,
                         "uri": "lb://customers-service"},
                  evidence=["spring-petclinic-api-gateway/src/main/resources/application.yml:30"]),
            claim("svcname", "consumes", "discovery:customers-service",
                  repo="repo_ms", hint="customers-service",
                  hint_source="discovery"),
        ])

    def test_route_claim_becomes_routes_to_with_rewrite_table(self):
        c = ctx()
        index = self._index()
        r0_alias.resolve(index, c)
        out = r4_gateway.resolve(index, c)
        routes = [e for e in out.edges if e.type == "ROUTES_TO"]
        assert len(routes) == 1
        edge = routes[0]
        assert edge.source_id == "global:Service:api-gateway"
        assert edge.target_id == "global:Service:customers-service"
        assert edge.extra_props["path_prefix"] == "/api/customer"
        assert edge.extra_props["strip_path"] == 2
        rules = c.rewrite_routes["api-gateway"]
        assert len(rules) == 1 and rules[0].target_name == "customers-service"
        gateways = [s for s in out.services if s.is_gateway]
        assert [g.service_id for g in gateways] == ["global:Service:api-gateway"]

    def test_unminted_target_stays_servicename_dead_end(self):
        c = ctx()
        index = ClaimIndex([
            app_name("api-gateway", "repo_ms"),
            claim("route", "consumes", "/api/vets/**→svcname:vets-service",
                  repo="repo_ms", hint="api-gateway", hint_source="config",
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestNonSpringProviderScope:
    """Regression: R7 keyed provider contracts on repo_id unless the provider
    declared spring.application.name, so no non-JVM service could ever be the
    target of a cross-repo HTTP match (the flagship VQ1 path)."""

    @staticmethod
    def _run(claims):
        from tracekite.services.linker import r7_http
        from tracekite.services.linker.base import ResolverOutput
        c = ctx()
        index = ClaimIndex(claims)
        out = ResolverOutput()
        for module in (r0_alias, r1_compose, r4_gateway):
            out.extend(module.resolve(index, c))
        c.normalized_calls = normalize_http_calls(index, c)
        out.extend(r7_http.resolve(index, c))
        return c, out

    @staticmethod
    def _consumer(repo="repo_web"):
        return [
            claim("http", "consumes", "httpcall:GET:/v1/orders", repo=repo,
                  hint="orders", hint_source="host",
                  evidence=[f"{repo}/src/client.py:9"], enode="node:callsite"),
            claim("svcname", "consumes", "discovery:orders", repo=repo,
                  hint="orders", hint_source="host",
                  evidence=[f"{repo}/src/client.py:9"]),
        ]

    def test_compose_provider_matches(self):
        claims = [
            claim("svcname", "provides", "proj:orders", repo="repo_orders",
                  attrs={"source": "compose", "build_context": "."},
                  evidence=["repo_orders/docker-compose.yml:3"]),
            claim("http", "provides", "GET:/v1/orders", repo="repo_orders",
                  evidence=["repo_orders/src/api.py:5"], enode="node:endpoint"),
            *self._consumer(),
        ]
        _, out = self._run(claims)
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert len(invokes) == 1
        assert invokes[0].target_id == "global:Http:orders:GET:/v1/orders"
        assert invokes[0].cross_repo is True

    def test_compose_provider_without_build_context_matches(self):
        claims = [
            claim("svcname", "provides", "proj:orders", repo="repo_orders",
                  attrs={"source": "compose"},
                  evidence=["repo_orders/docker-compose.yml:3"]),
            claim("http", "provides", "GET:/v1/orders", repo="repo_orders",
                  evidence=["repo_orders/src/api.py:5"], enode="node:endpoint"),
            *self._consumer(),
        ]
        _, out = self._run(claims)
        assert len([e for e in out.edges if e.type == "INVOKES"]) == 1

    def test_monorepo_build_contexts_scope_per_module(self):
        claims = [
            claim("svcname", "provides", "proj:orders", repo="mono",
                  attrs={"source": "compose", "build_context": "./services/orders"},
                  # Repo-relative, as real scans emit: the compose sits at the
                  # repo root and its contexts name the service directories.
                  evidence=["docker-compose.yml:3"]),
            claim("svcname", "provides", "proj:billing", repo="mono",
                  attrs={"source": "compose", "build_context": "./services/billing"},
                  evidence=["docker-compose.yml:9"]),
            claim("http", "provides", "GET:/v1/orders", repo="mono",
                  evidence=["services/orders/api.py:5"], enode="node:o"),
            claim("http", "provides", "GET:/v1/invoices", repo="mono",
                  evidence=["services/billing/api.py:5"], enode="node:b"),
        ]
        _, out = self._run(claims)
        contracts = sorted(r.node_id for r in out.rendezvous
                           if r.label == "HttpContract")
        assert contracts == ["global:Http:billing:GET:/v1/invoices",
                             "global:Http:orders:GET:/v1/orders"]

    def test_nested_compose_build_context_resolves_against_its_file(self):
        """Compose resolves `build: .` against the FILE, not the repo root.
        Resolved against the root, every nested service lands at "" rank 2,
        they tie, every lookup declines, and a monorepo's calls silently
        lose their consumers — found at 1,000 repos by the synthetic estate,
        where all 118 missing edges had monorepo consumers."""
        claims = [
            claim("svcname", "provides", "proj:orders", repo="mono",
                  attrs={"source": "compose", "build_context": "."},
                  evidence=["services/orders/docker-compose.yml:2"]),
            claim("svcname", "provides", "proj:billing", repo="mono",
                  attrs={"source": "compose", "build_context": "."},
                  evidence=["services/billing/docker-compose.yml:2"]),
            claim("http", "provides", "GET:/v1/orders", repo="mono",
                  evidence=["services/orders/api.py:5"], enode="node:o"),
            claim("http", "provides", "GET:/v1/invoices", repo="mono",
                  evidence=["services/billing/api.py:5"], enode="node:b"),
        ]
        _, out = self._run(claims)
        contracts = sorted(r.node_id for r in out.rendezvous
                           if r.label == "HttpContract")
        assert contracts == ["global:Http:billing:GET:/v1/invoices",
                             "global:Http:orders:GET:/v1/orders"]

    def test_build_context_escaping_the_repo_scopes_nothing(self):
        """`build: ../elsewhere` names a directory outside the repository.
        Pinning rank-2 evidence to a path that does not exist in the repo
        would attribute whatever happens to sit at the normalised string;
        the honest scope is the whole repo at the lowest rank, counted."""
        claims = [
            claim("svcname", "provides", "proj:orders", repo="mono",
                  # From the repo root, `..` leaves the repository. (From a
                  # nested compose, `deploy/../elsewhere` is just `elsewhere`
                  # — a legitimate in-repo directory — so only a normalised
                  # path still starting with `..` is actually outside.)
                  attrs={"source": "compose", "build_context": "../elsewhere"},
                  evidence=["docker-compose.yml:2"]),
            claim("http", "provides", "GET:/v1/orders", repo="mono",
                  evidence=["services/orders/api.py:5"], enode="node:o"),
        ]
        ctx_, out = self._run(claims)
        assert ctx_.counters.get("r0.build_context_outside_repo") == 1
        assert ctx_.module_services["mono"] == [("", "orders", 0)]

    def test_ambiguous_whole_repo_scope_declines(self):
        # Two services claim the whole repo with equal evidence: attributing a
        # contract to either would be a guess, so scope falls back to repo_id.
        claims = [
            claim("svcname", "provides", "proj:orders", repo="repo_x",
                  attrs={"source": "compose"},
                  evidence=["repo_x/docker-compose.yml:3"]),
            claim("svcname", "provides", "proj:billing", repo="repo_x",
                  attrs={"source": "compose"},
                  evidence=["repo_x/docker-compose.yml:9"]),
            claim("http", "provides", "GET:/v1/orders", repo="repo_x",
                  evidence=["repo_x/src/api.py:5"], enode="node:e"),
        ]
        c, out = self._run(claims)
        contracts = [r.node_id for r in out.rendezvous if r.label == "HttpContract"]
        assert contracts == ["global:Http:repo_x:GET:/v1/orders"]
        assert c.counters["scope.ambiguous"] > 0

    def test_config_repo_does_not_claim_scope(self):
        # A Spring Cloud Config repo holding customers-service.yml must not
        # scope its own HTTP endpoints as customers-service.
        claims = [
            claim("svcname", "provides", "discovery:customers-service",
                  repo="repo_cfg", attrs={"source": "config-filename"},
                  evidence=["customers-service.yml:1"]),
            claim("http", "provides", "GET:/actuator/health", repo="repo_cfg",
                  evidence=["repo_cfg/src/app.py:2"], enode="node:h"),
        ]
        _, out = self._run(claims)
        contracts = [r.node_id for r in out.rendezvous if r.label == "HttpContract"]
        assert contracts == ["global:Http:repo_cfg:GET:/actuator/health"]


class TestR7QualifyFromConfig:
    """A dependency-injected client has no literal host, so its call site is
    path-only. The callee is recovered by joining what the code READS from
    configuration to what compose says those keys point at."""

    def _env_host(self, env_key, host, repo="repo_caller", frm="caller"):
        return claim("svcname", "consumes", f"discovery:{host}", repo=repo,
                     hint=host, hint_source="config",
                     attrs={"via": "env_host", "env_key": env_key, "from": frm},
                     evidence=["docker-compose.yml:10"])

    def _cfgread(self, env_key, path, repo="repo_caller"):
        return claim("cfgread", "consumes", f"{repo}:{env_key}", repo=repo,
                     evidence=[f"{path}:3"])

    def _call(self, template="/v1/callers", repo="repo_caller",
              path="svc/clients/registry.py", base_var="registry"):
        return claim("http", "consumes", f"httpcall:GET:{template}", repo=repo,
                    attrs={"base_var": base_var}, evidence=[f"{path}:12"],
                    enode="node:call", etype="Method")

    def _provider(self, template="/v1/callers", repo="repo_registry"):
        return [claim("svcname", "provides", "discovery:capability-registry",
                      repo=repo, attrs={"source": "spring.application.name"},
                      evidence=[f"{repo}/src/main/resources/application.yml:2"]),
                claim("http", "provides", f"GET:{template}", repo=repo,
                      evidence=[f"{repo}/Api.java:5"], enode="node:ep",
                      etype="ApiEndpoint")]

    def _run(self, claims):
        from tracekite.services.linker import r0_alias, r7_http
        c = ctx()
        index = ClaimIndex(claims)
        r0_alias.resolve(index, c)
        c.normalized_calls = normalize_http_calls(index, c)
        return r7_http.resolve(index, c), c

    def test_path_only_call_is_qualified_from_config(self):
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._cfgread("CAPABILITY_REGISTRY_URL", "svc/config.py"),
            self._call(),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_config") == 1
        assert any(e.type == "INVOKES" for e in out.edges)

    def test_two_service_urls_in_scope_declines(self):
        # The module reads two service URLs and the variable name matches
        # neither: guessing would be a coin flip.
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._env_host("FOYER_ORCHESTRATOR_URL", "orchestrator"),
            self._cfgread("CAPABILITY_REGISTRY_URL", "svc/config.py"),
            self._cfgread("FOYER_ORCHESTRATOR_URL", "svc/config.py"),
            self._call(base_var="thing"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.config_scope_ambiguous") == 1
        assert c.counters.get("r7.qualified_by_config") is None
        assert not [e for e in out.edges if e.type == "INVOKES"]

    def test_multi_word_service_narrows_despite_separators(self):
        """`self._capability_registry_url` yields base_var
        `capability_registry`; the service is spelled `capability-registry`.
        Comparing raw-vs-squashed can never match a multi-word name, which
        silently disabled the tie-break for exactly the services distinctive
        enough to make it safe — found by the synthetic estate, where
        every consumer reads several *_URL keys from one directory."""
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._env_host("FOYER_ORCHESTRATOR_URL", "orchestrator"),
            self._cfgread("CAPABILITY_REGISTRY_URL", "svc/config.py"),
            self._cfgread("FOYER_ORCHESTRATOR_URL", "svc/config.py"),
            self._call(base_var="capability_registry"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_config_var") == 1
        assert any(e.type == "INVOKES" for e in out.edges)

    def test_a_var_matching_two_services_still_declines(self):
        """Squashing both sides erases separator differences and nothing
        else: a name contained in two candidates is still ambiguous, and
        guessing between orders-api and orders-api-v2 would assert an edge
        a coin flip could contradict."""
        claims = [
            *self._provider(),
            self._env_host("ORDERS_API_URL", "orders-api"),
            self._env_host("ORDERS_API_V2_URL", "orders-api-v2"),
            self._cfgread("ORDERS_API_URL", "svc/config.py"),
            self._cfgread("ORDERS_API_V2_URL", "svc/config.py"),
            self._call(base_var="orders_api"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_config_var") is None
        assert not [e for e in out.edges if e.type == "INVOKES"]

    def test_base_var_breaks_a_tie_but_never_decides_alone(self):
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._env_host("FOYER_ORCHESTRATOR_URL", "orchestrator"),
            self._cfgread("CAPABILITY_REGISTRY_URL", "svc/config.py"),
            self._cfgread("FOYER_ORCHESTRATOR_URL", "svc/config.py"),
            self._call(base_var="registry"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_config_var") == 1
        assert any(e.type == "INVOKES" for e in out.edges)

    def test_no_config_read_and_no_distinctive_var_stays_unqualified(self):
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            # `url` names nothing; with no config read above the call site
            # there is no evidence left to identify the callee.
            self._call(path="other/tree/client.py", base_var="url"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.unqualified") == 1
        assert not [e for e in out.edges if e.type == "INVOKES"]

    def test_no_config_read_but_distinctive_var_uses_the_fallback(self):
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._call(path="other/tree/client.py", base_var="registry"),
        ]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_var_only") == 1
        assert c.counters.get("r7.qualified_by_config") is None

    def test_config_derived_edge_records_its_provenance(self):
        claims = [
            *self._provider(),
            self._env_host("CAPABILITY_REGISTRY_URL", "capability-registry"),
            self._cfgread("CAPABILITY_REGISTRY_URL", "svc/config.py"),
            self._call(),
        ]
        out, _ = self._run(claims)
        invokes = [e for e in out.edges if e.type == "INVOKES"]
        assert invokes and "config_host" in (invokes[0].extra_props.get("via") or [])


class TestR7QualifyByVarOnly:
    """Fallback for call sites whose config module is not an ancestor — still
    requires the variable name to single out one declared service URL."""

    def _base(self):
        return [
            claim("svcname", "provides", "discovery:capability-registry",
                  repo="repo_registry", attrs={"source": "spring.application.name"},
                  evidence=["repo_registry/src/main/resources/application.yml:2"]),
            claim("http", "provides", "GET:/v1/callers", repo="repo_registry",
                  evidence=["repo_registry/Api.java:5"], enode="node:ep",
                  etype="ApiEndpoint"),
            claim("svcname", "consumes", "discovery:capability-registry",
                  repo="repo_caller", hint="capability-registry", hint_source="config",
                  attrs={"via": "env_host", "env_key": "CAPABILITY_REGISTRY_URL",
                         "from": "caller"},
                  evidence=["docker-compose.yml:10"]),
        ]

    def _run(self, claims):
        from tracekite.services.linker import r0_alias, r7_http
        c = ctx()
        index = ClaimIndex(claims)
        r0_alias.resolve(index, c)
        c.normalized_calls = normalize_http_calls(index, c)
        return r7_http.resolve(index, c), c

    def test_unique_var_match_qualifies(self):
        claims = [*self._base(),
                  claim("http", "consumes", "httpcall:GET:/v1/callers",
                        repo="repo_caller", attrs={"base_var": "registry"},
                        evidence=["far/away/client.py:9"], enode="node:c",
                        etype="Method")]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_var_only") == 1
        assert any(e.type == "INVOKES" for e in out.edges)

    def test_two_matching_env_vars_decline(self):
        claims = [*self._base(),
                  claim("svcname", "consumes", "discovery:other-registry",
                        repo="repo_caller", hint="other-registry",
                        hint_source="config",
                        attrs={"via": "env_host", "env_key": "OTHER_REGISTRY_URL",
                               "from": "caller"},
                        evidence=["docker-compose.yml:12"]),
                  claim("http", "consumes", "httpcall:GET:/v1/callers",
                        repo="repo_caller", attrs={"base_var": "registry"},
                        evidence=["far/away/client.py:9"], enode="node:c",
                        etype="Method")]
        out, c = self._run(claims)
        assert c.counters.get("r7.var_only_ambiguous") == 1
        assert c.counters.get("r7.qualified_by_var_only") is None

    def test_short_or_generic_var_never_qualifies(self):
        # `url`, `api` and friends carry no service identity.
        claims = [*self._base(),
                  claim("http", "consumes", "httpcall:GET:/v1/callers",
                        repo="repo_caller", attrs={"base_var": "url"},
                        evidence=["far/away/client.py:9"], enode="node:c",
                        etype="Method")]
        out, c = self._run(claims)
        assert c.counters.get("r7.qualified_by_var_only") is None
        assert c.counters.get("r7.unqualified") == 1


class TestI9KeyFinality:
    """Invariant I9: rendezvous keys are final once NORMALIZE completes.

    The failure this guards against is silent. A joining resolver run without
    NORMALIZE finds no frozen keys, emits nothing, and reports success — an
    empty graph indistinguishable from an estate with no connections. So the
    unset state must be loud, and the phase order must live in one place.
    """

    def test_joining_without_normalize_raises_rather_than_emitting_nothing(self):
        from tracekite.services.linker import r7_http
        c = ctx()
        index = ClaimIndex([])
        with pytest.raises(RuntimeError, match="NORMALIZE has not run"):
            r7_http.resolve(index, c)

    def test_run_resolvers_freezes_keys_before_the_join(self):
        from tracekite.services.linker.engine import run_resolvers
        c = ctx()
        run_resolvers(ClaimIndex([]), c)
        # Populated, not merely absent-and-tolerated.
        assert c.normalized_calls == {}

    def test_broadcast_runs_before_join(self):
        from tracekite.services.linker.engine import (
            BROADCAST_RESOLVERS, JOIN_RESOLVERS, RESOLVERS,
        )
        names = [n for n, _ in RESOLVERS]
        # r4 builds the route table NORMALIZE rewrites through, so it must
        # land in the broadcast group; r7 consumes frozen keys, so it must not.
        assert "r4_gateway" in [n for n, _ in BROADCAST_RESOLVERS]
        assert "r7_http" in [n for n, _ in JOIN_RESOLVERS]
        assert names == [n for n, _ in BROADCAST_RESOLVERS] + \
                        [n for n, _ in JOIN_RESOLVERS]
