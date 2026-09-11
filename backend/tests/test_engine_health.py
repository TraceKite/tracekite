"""The library can be asked whether it is degraded.

The failure modes this catches are quiet: an unset HMAC key means redaction
refuses at the first secret, and a missing confidence table means every score
would be a guess. Both surface deep in a run rather than at startup, which is
when a host can do least about them.
"""

import dataclasses

import pytest

from tracekite import engine_config
from tracekite.engine_health import DEGRADED, FAILED, OK, health


@pytest.fixture
def configured(monkeypatch):
    def apply(**overrides):
        monkeypatch.setattr(
            engine_config, "_active",
            dataclasses.replace(engine_config.get_config(), **overrides))
    return apply


class TestHealthCall:
    def test_a_configured_engine_is_ok(self, configured):
        configured(graph_hmac_key="health-test-key")
        report = health()
        assert report.ok, report.as_dict()

    def test_an_unset_hmac_key_fails_at_startup_not_mid_scan(self, configured):
        configured(graph_hmac_key="")
        report = health()
        assert report.status == FAILED
        assert any(c.name == "redaction_key" and c.status == FAILED
                   for c in report.checks)

    def test_a_missing_control_plane_fails(self, configured):
        """link() refuses to run on uncalibrated confidences, so an engine
        that cannot load the table cannot answer at all."""
        configured(graph_hmac_key="k", config_dir="/nonexistent/control/plane")
        report = health()
        assert report.status == FAILED
        assert any(c.name == "control_plane" for c in report.checks)

    def test_an_unwritable_workspace_is_degraded_not_failed(self, configured):
        """Scanning a path in place still works; only cloning breaks."""
        configured(graph_hmac_key="k", workspace_dir="/nonexistent/workspace")
        report = health()
        assert report.status == DEGRADED
        assert any(c.name == "workspace" and c.status == DEGRADED
                   for c in report.checks)

    def test_the_worst_check_decides_the_verdict(self, configured):
        configured(graph_hmac_key="", workspace_dir="/nonexistent")
        assert health().status == FAILED, "failed must outrank degraded"

    def test_every_check_says_what_it_looked_at(self, configured):
        """A status with no detail is an opinion, not a diagnosis."""
        configured(graph_hmac_key="")
        for check in health().checks:
            if check.status != OK:
                assert check.detail, check.name

    def test_storage_is_only_checked_when_supplied(self, configured):
        """A host that keeps no storage is in its intended state, not
        broken."""
        configured(graph_hmac_key="k")
        assert not any(c.name == "store" for c in health().checks)

    def test_a_working_store_is_reported(self, configured):
        from tracekite.db.memory_store import InMemoryGraphStore

        configured(graph_hmac_key="k")
        report = health(store=InMemoryGraphStore())
        assert any(c.name == "store" and c.status == OK
                   for c in report.checks)

    def test_a_broken_store_fails_rather_than_raising(self, configured):
        """A health call that raises tells a host nothing it can act on."""
        class Broken:
            def query(self, spec):
                raise RuntimeError("connection refused")

        configured(graph_hmac_key="k")
        report = health(store=Broken())
        assert report.status == FAILED
        assert any(c.name == "store" and "connection refused" in c.detail
                   for c in report.checks)

    def test_the_report_serialises(self, configured):
        configured(graph_hmac_key="k")
        payload = health().as_dict()
        assert payload["status"] in (OK, DEGRADED, FAILED)
        assert all({"name", "status", "detail"} == set(c)
                   for c in payload["checks"])
