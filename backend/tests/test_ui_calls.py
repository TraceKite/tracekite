"""A frontend component resolves to a backend endpoint.

The join is the one r7 already performs; what C1 adds is the TYPE — a
blast radius that cannot tell a service caller from a browser component
overstates one and hides the other. So the tests are mostly about who gets
marked: a UI-only hook anywhere, any call in a component file, and nothing
else — a plain fetch() in ordinary .ts is a Node service's call shape too,
and typing it by folklore would be a guessed edge.
"""

from tracekite.services.http_call_extractor import extract_http_calls
from tracekite.services.linker.base import ClaimIndex, ClaimRecord, LinkContext
from tracekite.services.linker.engine import link


def claim(cid, repo, kind, direction, key, *, hint=None, src="none",
          attrs=None, ev="src/App.tsx:5", node=None):
    return ClaimRecord(
        id=cid, repo_id=repo, kind=kind, direction=direction, key=key,
        service_hint=hint, hint_source=src, matchable=True,
        evidence=[ev], attrs=attrs or {},
        evidence_node_id=node or f"node:{cid}", evidence_node_type="File")


class TestMarking:
    def test_a_ui_only_hook_is_ui_wherever_it_lives(self):
        sites = extract_http_calls(
            "src/hooks/useOwners.ts",
            'const { data } = useSWR("/api/owners")', "typescript")
        assert sites and sites[0].attrs.get("ui") is True

    def test_any_call_in_a_component_file_is_ui(self):
        sites = extract_http_calls(
            "src/OwnersPage.tsx",
            'fetch("http://billing:8080/v1/owners")', "typescript")
        assert sites and sites[0].attrs.get("ui") is True

    def test_a_plain_fetch_in_ordinary_ts_is_not_ui(self):
        """A Node service uses the same call shape; marking it would type
        the edge by folklore rather than evidence."""
        sites = extract_http_calls(
            "src/server/proxy.ts",
            'fetch("http://billing:8080/v1/owners")', "typescript")
        assert sites and "ui" not in sites[0].attrs


class TestEdgeType:
    def _run(self, consumer_attrs):
        claims = [
            claim("p1", "repo_api", "svcname", "provides",
                  "discovery:billing", hint="billing", src="config",
                  ev="deploy/app.yml:1"),
            claim("r1", "repo_api", "http", "provides", "GET:/v1/owners",
                  hint="billing", src="config", ev="src/api.py:3"),
            claim("c1", "repo_web", "http", "consumes",
                  "httpcall:GET:/v1/owners", hint="billing", src="host",
                  attrs=consumer_attrs),
            # The consumer side's own service, so the rollup can attribute
            # the calling file to a Service node.
            claim("w1", "repo_web", "svcname", "provides", "prod:web",
                  hint="web", src="config", ev="deploy/web.yml:1",
                  attrs={"source": "k8s", "workload": "web"}),
        ]
        return link(claims, run_id="linkrun_ui", confidence={}, aliases={},
                    promotions=[], now="2026-01-01T00:00:00+00:00")

    def test_a_ui_call_site_emits_ui_calls_at_the_same_tier(self):
        result = self._run({"ui": True})
        ui = [e for e in result.edges if e.type == "UI_CALLS"]
        assert len(ui) == 1
        assert ui[0].match_type == "hint_exact"
        assert result.counters["r7.ui_calls"] == 1
        assert not [e for e in result.edges if e.type == "INVOKES"]

    def test_a_service_call_site_still_emits_invokes(self):
        result = self._run({})
        assert [e.type for e in result.edges
                if e.type in ("INVOKES", "UI_CALLS")] == ["INVOKES"]
        assert "r7.ui_calls" not in result.counters

    def test_the_join_and_confidence_are_identical_either_way(self):
        """The type is the ONLY difference: same contract, same tier, same
        confidence. A UI edge priced differently would make filtering by
        type silently change what the numbers mean."""
        ui = [e for e in self._run({"ui": True}).edges
              if e.type == "UI_CALLS"][0]
        service = [e for e in self._run({}).edges
                   if e.type == "INVOKES"][0]
        assert (ui.target_id, ui.confidence, ui.match_type) \
            == (service.target_id, service.confidence, service.match_type)

    def test_ui_calls_still_roll_up_to_the_service_graph(self):
        """Switching the site-level type must not cost the service-level
        edge — that would trade a feature for a recall regression."""
        result = self._run({"ui": True})
        calls = [e for e in result.edges if e.type == "CALLS_SERVICE"]
        assert calls, [e.type for e in result.edges]

    def test_a_ui_consumer_still_blocks_a_deprecation(self):
        from tracekite.services.linker.deprecations import deprecation_report

        result = self._run({"ui": True})
        for spec in result.rendezvous:
            if spec.label == "HttpContract":
                spec.props["deprecated"] = True
        report = deprecation_report(result.edges, result.rendezvous)
        assert report and report[0]["safe_to_remove"] is False


class TestEndToEnd:
    def test_a_component_resolves_to_a_backend_endpoint(self, tmp_path):
        """The exit criterion, through the real pipeline: a .tsx component
        fetches, the provider registers the route, the edge is UI_CALLS
        with file:line on both sides."""
        from tracekite import engine_config
        from tracekite.db.memory_store import InMemoryLinkerStore
        from tracekite.services.scan import scan

        engine_config.configure(graph_hmac_key="ui-calls-test")
        web = tmp_path / "web"
        (web / "src").mkdir(parents=True)
        (web / "docker-compose.yml").write_text(
            "services:\n  web-app:\n    build: .\n    environment:\n"
            "      BILLING_URL: http://billing-service:8080\n")
        (web / "src" / "OwnersPage.tsx").write_text(
            'export function OwnersPage({ id }) {\n'
            '  fetch(`http://billing-service:8080/v1/invoices/${id}`);\n'
            '  return null;\n}\n')

        billing = tmp_path / "billing"
        (billing / "internal").mkdir(parents=True)
        (billing / "docker-compose.yml").write_text(
            'services:\n  billing-service:\n    build: .\n    ports:\n'
            '      - "8080:8080"\n')
        (billing / "internal" / "routes.go").write_text(
            'package internal\n\nimport "net/http"\n\n'
            'func Register(mux *http.ServeMux) {\n'
            '\tmux.HandleFunc("GET /v1/invoices/{id}", handle)\n}\n\n'
            'func handle(w http.ResponseWriter, r *http.Request) {}\n')

        sinks = [scan(str(web), "web"), scan(str(billing), "billing")]
        result = link(InMemoryLinkerStore(sinks).load_claims(),
                      run_id="linkrun_c1",
                      now="2026-01-01T00:00:00+00:00")
        ui = [e for e in result.edges
              if e.type == "UI_CALLS" and e.status == "active"]
        assert ui, sorted({e.type for e in result.edges})
        assert "billing" in ui[0].target_id
        assert any("OwnersPage.tsx" in cite for cite in ui[0].evidence)
