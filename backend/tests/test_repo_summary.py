"""Repo property mapping stays independent of the Neo4j reader."""

from datetime import datetime, timezone

from tracekite.services.repo_summary import repo_summary


class _Temporal:
    def __init__(self, value):
        self._value = value

    def to_native(self):
        return self._value


def test_repo_summary_preserves_explicit_upload_source():
    summary = repo_summary({
        "id": "local_demo",
        "name": "local/demo",
        "owner": "local",
        "repo": "demo",
        "github_url": "",
        "branch": "abc1234",
        "ingestion_status": "completed",
        "source": "upload",
        "parse_coverage_totals": '{"files_seen": 2}',
        "claims_by_kind": '{"http_call": 1}',
    })

    assert summary.source == "upload"
    assert summary.github_url == ""
    assert summary.branch == "abc1234"
    assert summary.parse_coverage == {"files_seen": 2}
    assert summary.claims_by_kind == {"http_call": 1}


def test_repo_summary_keeps_failed_hosted_source_unknown():
    stamp = datetime(2026, 9, 13, tzinfo=timezone.utc)
    summary = repo_summary({
        "id": "owner_missing",
        "ingestion_status": "failed",
        "lifecycle_state": "failed_clean",
        "last_ingested_at": _Temporal(stamp),
    })

    assert summary.source is None
    assert summary.github_url == ""
    assert summary.branch == "main"
    assert summary.last_ingested_at == stamp
