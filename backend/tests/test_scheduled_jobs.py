"""Schedules produce edges.

A time-triggered dependency is still a dependency — and a different risk:
breaking it fails nothing until 03:00. So the edge must exist AND carry
its trigger, because "billing calls refresh nightly" and "billing calls
refresh on every request" are different findings wearing the same arrow.
"""

from evigraph import engine_config
from evigraph.db.memory_store import InMemoryLinkerStore, claims_from_scan
from evigraph.parsers.cron_parser import parse_crontab
from evigraph.services.linker.engine import link
from evigraph.services.scan import scan

NOW = "2026-01-01T00:00:00+00:00"


class TestCronParser:
    def test_a_curl_line_yields_schedule_method_and_url(self):
        [call] = parse_crontab(
            "cron.d/nightly",
            "0 3 * * * app curl -X POST http://billing:8080/v1/refresh\n")
        assert (call.schedule, call.method, call.url, call.line) == \
            ("0 3 * * *", "POST", "http://billing:8080/v1/refresh", 1)

    def test_shortcut_schedules_parse(self):
        [call] = parse_crontab("crontab",
                               "@hourly curl http://metrics:9090/rollup\n")
        assert call.schedule == "@hourly" and call.method == "GET"

    def test_a_script_line_is_not_guessed_at(self):
        """The script might call anything; might is not evidence."""
        assert parse_crontab("crontab",
                             "*/5 * * * * /usr/local/bin/cleanup.sh\n") == []

    def test_comments_and_variable_lines_are_skipped(self):
        assert parse_crontab(
            "crontab",
            "# nightly\nSHELL=/bin/sh\nMAILTO=ops@example.com\n") == []

    def test_an_ordinary_file_is_not_a_crontab(self):
        """`5 4 * * * curl ...` inside a README is documentation."""
        assert parse_crontab(
            "README.md", "0 3 * * * curl http://x:1/y\n") == []


class TestClaims:
    def test_a_scanned_crontab_claims_the_call_with_its_trigger(
            self, tmp_path):
        engine_config.configure(graph_hmac_key="cron-claims-test")
        (tmp_path / "cron.d").mkdir()
        (tmp_path / "cron.d" / "nightly").write_text(
            "0 3 * * * app curl -X POST "
            "http://billing-service:8080/v1/refresh\n")
        claims = claims_from_scan(scan(str(tmp_path), "ops"))
        [call] = [c for c in claims if c.kind == "http"]
        assert call.key == "httpcall:POST:/v1/refresh"
        assert call.service_hint == "billing-service"
        assert call.attrs["schedule"] == "0 3 * * *"
        assert call.evidence == ["cron.d/nightly:1"]


class TestEdges:
    def test_a_cronjob_env_host_edge_carries_the_trigger(self, tmp_path):
        """k8s CronJob -> literal env host -> CALLS_SERVICE, stamped with
        the cron expression rather than presented as an always-on call."""
        engine_config.configure(graph_hmac_key="cronjob-test")
        (tmp_path / "deploy").mkdir()
        (tmp_path / "deploy" / "jobs.yaml").write_text("""
apiVersion: batch/v1
kind: CronJob
metadata: {name: invoice-refresher, namespace: prod}
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: refresher
              image: registry.internal/org/refresher:1
              env:
                - name: BILLING_URL
                  value: http://billing.prod.svc.cluster.local:8080
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: billing, namespace: prod}
spec:
  template:
    metadata: {labels: {app: billing}}
    spec:
      containers: [{name: app, image: registry.internal/org/billing:1}]
---
apiVersion: v1
kind: Service
metadata: {name: billing, namespace: prod}
spec: {selector: {app: billing}, ports: [{port: 8080}]}
""")
        store = InMemoryLinkerStore([scan(str(tmp_path), "deploy_repo")])
        result = link(store.load_claims(), run_id="linkrun_cron", now=NOW)
        calls = [e for e in result.edges
                 if e.type == "CALLS_SERVICE" and e.status == "active"]
        assert calls, result.counters
        assert calls[0].extra_props.get("schedule") == "0 3 * * *"
        assert result.counters.get("r2.scheduled_calls") == 1

    def test_a_crontab_call_joins_a_provider_with_the_trigger(self, tmp_path):
        """Crontab consumer, Go provider: the INVOKES edge carries the
        schedule with file:line on both sides."""
        engine_config.configure(graph_hmac_key="crontab-join-test")
        ops = tmp_path / "ops"
        (ops / "cron.d").mkdir(parents=True)
        (ops / "cron.d" / "nightly").write_text(
            "0 3 * * * app curl -X POST "
            "http://billing-service:8080/v1/refresh\n")

        billing = tmp_path / "billing"
        (billing / "internal").mkdir(parents=True)
        (billing / "docker-compose.yml").write_text(
            'services:\n  billing-service:\n    build: .\n    ports:\n'
            '      - "8080:8080"\n')
        (billing / "internal" / "routes.go").write_text(
            'package internal\n\nimport "net/http"\n\n'
            'func Register(mux *http.ServeMux) {\n'
            '\tmux.HandleFunc("POST /v1/refresh", handle)\n}\n\n'
            'func handle(w http.ResponseWriter, r *http.Request) {}\n')

        store = InMemoryLinkerStore([scan(str(ops), "ops"),
                                     scan(str(billing), "billing")])
        result = link(store.load_claims(), run_id="linkrun_ct", now=NOW)
        invokes = [e for e in result.edges
                   if e.type == "INVOKES" and e.status == "active"]
        assert invokes, result.counters
        assert invokes[0].extra_props.get("schedule") == "0 3 * * *"
        assert any("cron.d/nightly:1" in cite for cite in invokes[0].evidence)

    def test_an_unscheduled_call_carries_no_schedule(self):
        """Empty means "not scheduled"; stamping one would invent a
        trigger."""
        engine_config.configure(graph_hmac_key="cron-neg-test")
        import os
        corpus = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")
        store = InMemoryLinkerStore([
            scan(os.path.join(corpus, "orders-service"), "orders-service"),
            scan(os.path.join(corpus, "billing-service"), "billing-service")])
        result = link(store.load_claims(), run_id="linkrun_plain", now=NOW)
        assert all("schedule" not in (e.extra_props or {})
                   for e in result.edges)
