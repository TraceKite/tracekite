"""Declared vs observed reconciled, both sides cited.

Two directions of drift, two different findings: a promise nobody keeps
(declared-not-observed — a consumer built against the spec 404s) and an
endpoint nobody documents (observed-not-declared — undocumented coupling).
The precision pin matters most: a spec must never MINT a contract.
"""

from types import SimpleNamespace

from tracekite import engine_config
from tracekite.db.memory_store import InMemoryLinkerStore, claims_from_scan
from tracekite.services.linker.engine import link
from tracekite.services.linker.reconciliation import reconcile
from tracekite.services.scan import scan

SPEC = """openapi: 3.0.0
info: {title: Billing API}
paths:
  /v1/invoices/{id}:
    get:
      summary: fetch one
  /v1/refunds:
    post:
      summary: declared but never implemented
"""

ROUTES = ('package internal\nimport "net/http"\n'
          'func R(m *http.ServeMux) {\n'
          '\tm.HandleFunc("GET /v1/invoices/{id}", h)\n'
          '\tm.HandleFunc("DELETE /v1/invoices/{id}", h)\n}\n'
          'func h(w http.ResponseWriter, r *http.Request) {}\n')


def scanned(tmp_path):
    engine_config.configure(graph_hmac_key="drift-test")
    (tmp_path / "internal").mkdir()
    (tmp_path / "openapi.yaml").write_text(SPEC)
    (tmp_path / "internal" / "routes.go").write_text(ROUTES)
    return scan(str(tmp_path), "billing")


class TestHttpDrift:
    def test_both_directions_with_citations(self, tmp_path):
        report = reconcile(claims_from_scan(scanned(tmp_path)))
        http = report["http"]
        assert [m["operation"] for m in http["matched"]] \
            == ["GET /v1/invoices/{}"]
        assert [d["operation"] for d in http["declared_not_observed"]] \
            == ["POST /v1/refunds"]
        assert [o["operation"] for o in http["observed_not_declared"]] \
            == ["DELETE /v1/invoices/{}"]
        # Both sides cited: the spec line and the code line.
        assert http["matched"][0]["declared"][0]["evidence"][0] \
            .startswith("openapi.yaml:")
        assert http["matched"][0]["observed"][0]["evidence"][0] \
            .startswith("internal/routes.go:")

    def test_param_names_do_not_count_as_drift(self, tmp_path):
        """/invoices/{invoiceId} in the spec meets /invoices/{id} in code:
        the name is documentation, the position is the contract."""
        engine_config.configure(graph_hmac_key="drift-test")
        (tmp_path / "internal").mkdir()
        (tmp_path / "openapi.yaml").write_text(
            SPEC.replace("{id}", "{invoiceId}"))
        (tmp_path / "internal" / "routes.go").write_text(ROUTES)
        report = reconcile(claims_from_scan(scan(str(tmp_path), "billing")))
        assert [m["operation"] for m in report["http"]["matched"]] \
            == ["GET /v1/invoices/{}"]


class TestSpecsNeverMint:
    def test_a_declared_operation_is_not_a_contract(self, tmp_path):
        """The precision pin: POST /v1/refunds exists only in the spec, and
        the linked graph must not contain a contract for it — a document
        saying so is not an endpoint existing."""
        sink = scanned(tmp_path)
        result = link(InMemoryLinkerStore([sink]).load_claims(),
                      run_id="linkrun_drift",
                      now="2026-01-01T00:00:00+00:00")
        refund_contracts = [s for s in result.rendezvous
                            if s.label == "HttpContract"
                            and "refunds" in s.node_id]
        assert refund_contracts == []

    def test_spec_claims_are_recorded_but_unmatchable(self, tmp_path):
        claims = [c for c in claims_from_scan(scanned(tmp_path))
                  if c.attrs.get("source") == "openapi"]
        assert claims, "spec produced no claims at all"
        assert all(not c.matchable for c in claims)


class TestOtherProtocols:
    def test_sections_exist_even_when_empty(self):
        report = reconcile([])
        for section in ("http", "grpc", "topics"):
            assert "declared_not_observed" in report[section]
            assert "observed_not_declared" in report[section]

    def test_a_served_proto_is_not_drift(self):
        # opentelemetry-demo: the proto declares `oteldemo.CartService/AddItem`,
        # the server names only `CartService`. Key for key they never met, so
        # every operation of a fully served proto was reported unkept.
        report = reconcile([
            _claim("grpcop", "provides", "oteldemo.CartService/AddItem"),
            _claim("grpcop", "provides", "oteldemo.CartService/GetCart"),
            _claim("grpcop", "provides", "oteldemo.AdService/GetAds"),
            _claim("grpcstub", "provides", "CartService"),
            _claim("grpcstub", "provides", "LegacyService"),
        ])["grpc"]

        assert report["matched"] == 2
        assert report["declared_not_observed"] == ["oteldemo.AdService/GetAds"]
        assert report["observed_not_declared"] == ["LegacyService"]

    def test_a_dynamic_topic_is_not_reported_as_a_topic_named_nothing(self):
        report = reconcile([
            _claim("topic", "provides", "", matchable=False),
            _claim("topic", "provides", "orders.created"),
        ])["topics"]

        assert report["observed_not_declared"] == ["orders.created"]


def _claim(kind, direction, key, matchable=True):
    return SimpleNamespace(kind=kind, direction=direction, key=key, attrs={},
                           matchable=matchable, evidence=[], repo_id="repo")
