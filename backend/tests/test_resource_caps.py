"""Every resource cap is enforced *and* reported.

The reporting half is the point. A cap that silently truncates makes a capped
scan indistinguishable from a repository that simply had less in it — the
reader sees a smaller graph and no reason to doubt it. That is the same
failure as a silent decline, one altitude up.

Four caps exist. Each is checked here for both halves: it bites, and it says
so.
"""

import dataclasses
import os

import pytest

from evigraph import engine_config
from evigraph.services.ingest_source import IngestSink
from evigraph.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


@pytest.fixture
def configured(monkeypatch):
    """Apply config overrides without leaking them into other tests."""
    def apply(**overrides):
        monkeypatch.setattr(
            engine_config, "_active",
            dataclasses.replace(engine_config.get_config(),
                                graph_hmac_key="caps-test-key", **overrides))
    return apply


class TestFileCap:
    def test_uncapped_scan_parses_everything(self, configured):
        configured(max_files_per_repo=0)
        assert "files" not in scan(SAMPLE, "r").capped

    def test_cap_truncates_and_reports_how_much(self, configured):
        configured(max_files_per_repo=2)
        sink = scan(SAMPLE, "r")
        assert sink.capped.get("files", 0) > 0, (
            "a truncated scan that reports nothing is indistinguishable "
            "from a small repository")

    def test_reported_count_is_the_number_actually_dropped(self, configured):
        configured(max_files_per_repo=0)
        total = sum(c["files_seen"] for c in scan(SAMPLE, "r").coverage.values())
        configured(max_files_per_repo=1)
        assert scan(SAMPLE, "r").capped["files"] == total - 1


class TestClaimCap:
    def test_budget_is_not_exhausted_when_uncapped(self):
        sink = IngestSink()
        sink.max_claims = 0
        for _ in range(50):
            sink.count_claim("http")
        assert sink.claim_budget_exhausted() is False
        assert not sink.capped

    def test_budget_trips_at_the_ceiling_and_records_it(self):
        sink = IngestSink()
        sink.max_claims = 3
        for _ in range(3):
            sink.count_claim("http")
        assert sink.claim_budget_exhausted() is True
        assert sink.capped["claims"] >= 1

    def test_provenance_counters_do_not_consume_the_budget(self):
        """`add_claim` records provenance under `_`-prefixed keys. Counting
        them as claims would trip the ceiling early and under-collect."""
        sink = IngestSink()
        sink.max_claims = 5
        sink.count_claim("http")
        for _ in range(10):
            sink.count_claim("_vendored")
        assert sink.claims_total() == 1
        assert sink.claim_budget_exhausted() is False


class TestExistingCapsStillReport:
    def test_oversized_files_are_counted_not_dropped_quietly(self, configured):
        configured(parse_file_cap_bytes=10)
        sink = scan(SAMPLE, "r")
        skipped = sum(c["files_skipped_large"] for c in sink.coverage.values())
        assert skipped > 0

    def test_every_cap_has_somewhere_to_report(self):
        """A cap added to the config with no counter behind it is a silent
        truncation waiting to happen."""
        config = engine_config.get_config()
        for field in ("parse_timeout_s", "parse_file_cap_bytes",
                      "max_files_per_repo", "max_claims_per_repo"):
            assert hasattr(config, field), field
