"""Provider shape changed, consumers not updated.

The report's precision lives in two refusals: it never PAIRS an old shape
to a new one (a wrong pairing migrates every consumer to the wrong
endpoint), and a removed operation with no remaining caller is a
completed migration, not drift.
"""

from adduce import engine_config
from adduce.db.memory_store import claims_from_scan
from adduce.services.linker.contract_drift import contract_drift
from adduce.services.scan import scan

PROVIDER_V1 = ('package internal\nimport "net/http"\n'
               'func R(m *http.ServeMux) {\n'
               '\tm.HandleFunc("GET /v1/owners/{id}", h)\n}\n'
               'func h(w http.ResponseWriter, r *http.Request) {}\n')
PROVIDER_V2 = PROVIDER_V1.replace("/v1/owners/{id}", "/v2/owners/{id}")

CONSUMER = ('import os\n\nimport httpx\n\n\nclass Client:\n'
            '    def __init__(self):\n'
            '        self._billing_url = os.environ["BILLING_URL"]\n\n'
            '    async def owner(self, oid):\n'
            '        return await httpx.AsyncClient().get(\n'
            '            f"{self._billing_url}/v1/owners/{oid}")\n')


def estate(tmp_path, name, provider_src, with_consumer=True):
    root = tmp_path / name
    (root / "billing" / "internal").mkdir(parents=True)
    (root / "billing" / "internal" / "routes.go").write_text(provider_src)
    claims = claims_from_scan(scan(str(root / "billing"), "billing"))
    if with_consumer:
        (root / "orders" / "src").mkdir(parents=True)
        (root / "orders" / "docker-compose.yml").write_text(
            "services:\n  orders:\n    build: .\n    environment:\n"
            "      BILLING_URL: http://billing:8080\n")
        (root / "orders" / "src" / "billing_client.py").write_text(CONSUMER)
        claims += claims_from_scan(scan(str(root / "orders"), "orders"))
    return claims


class TestDrift:
    def test_a_reshaped_operation_with_stale_callers_is_drift(self, tmp_path):
        engine_config.configure(graph_hmac_key="g3-test")
        base = estate(tmp_path, "base", PROVIDER_V1)
        head = estate(tmp_path, "head", PROVIDER_V2)
        report = contract_drift(base, head)

        [drift] = report["drifted"]
        assert drift["operation"] == "GET /v1/owners/{}"
        assert any("routes.go" in cite
                   for side in drift["was_provided_by"]
                   for cite in side["evidence"])
        assert any("billing_client.py" in cite
                   for side in drift["still_called_by"]
                   for cite in side["evidence"])
        # Context, never a pairing.
        assert report["added_operations"] == ["GET /v2/owners/{}"]

    def test_a_completed_migration_is_not_drift(self, tmp_path):
        """Operation removed, consumer gone too: reporting it would teach
        people to ignore the report."""
        engine_config.configure(graph_hmac_key="g3-test")
        base = estate(tmp_path, "base2", PROVIDER_V1)
        head = estate(tmp_path, "head2", PROVIDER_V2, with_consumer=False)
        report = contract_drift(base, head)
        assert report["drifted"] == []
        assert "GET /v1/owners/{}" in report["removed_without_callers"]

    def test_an_unchanged_provider_reports_nothing(self, tmp_path):
        engine_config.configure(graph_hmac_key="g3-test")
        base = estate(tmp_path, "base3", PROVIDER_V1)
        head = estate(tmp_path, "head3", PROVIDER_V1)
        report = contract_drift(base, head)
        assert report["drifted"] == []
        assert report["added_operations"] == []
