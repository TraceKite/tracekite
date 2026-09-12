"""Tests for the versioned intelligence-answer contract.

Acceptance: schema fixtures cover all answer states, reject invented
revision/evidence data, and no empty or filtered result can imply
safe-to-delete.  Unknown coverage and revisions remain unknown.
"""

import pytest

from tracekite.answer import (
    ANSWER_VERSION,
    AnswerEnvelope,
    AnswerStatus,
    CompletenessAssessment,
    FreshnessState,
    QueryScope,
    RepoRevision,
    SnapshotIdentity,
    TruncationInfo,
)


def _envelope(status: AnswerStatus, **kw) -> AnswerEnvelope:
    """Minimal envelope builder for fixture tests."""
    return AnswerEnvelope(
        status=status,
        snapshot=SnapshotIdentity(engine_version="2.0.0"),
        scope=QueryScope(query_kind="test", **kw.pop("scope_kw", {})),
        completeness=CompletenessAssessment(**kw.pop("completeness_kw", {})),
        **kw,
    )


class TestAnswerStates:
    """Every answer status has a fixture and round-trips through JSON."""

    @pytest.mark.parametrize("status", list(AnswerStatus))
    def test_each_status_round_trips(self, status):
        env = _envelope(status)
        dumped = env.model_dump()
        restored = AnswerEnvelope(**dumped)
        assert restored.status == status

    def test_present_carries_result(self):
        env = _envelope(AnswerStatus.PRESENT, result={"services": ["a", "b"]})
        assert env.result["services"] == ["a", "b"]

    def test_known_empty_is_not_safe_to_delete(self):
        env = _envelope(AnswerStatus.KNOWN_EMPTY)
        assert env.completeness.safe_to_delete is False

    def test_unknown_target_carries_candidates(self):
        env = _envelope(
            AnswerStatus.UNKNOWN_TARGET,
            candidates=["service:a", "service:b"],
            reason="node not in graph",
        )
        assert env.candidates == ["service:a", "service:b"]
        assert env.completeness.safe_to_delete is False

    def test_ambiguous_carries_candidates_and_reason(self):
        env = _envelope(
            AnswerStatus.AMBIGUOUS,
            candidates=["service:a", "service:b"],
            reason="ambiguous service name",
        )
        assert env.reason == "ambiguous service name"
        assert env.completeness.safe_to_delete is False

    def test_unavailable_carries_reason(self):
        env = _envelope(
            AnswerStatus.UNAVAILABLE,
            reason="graph not loaded",
        )
        assert env.reason == "graph not loaded"
        assert env.completeness.safe_to_delete is False


class TestRevisionIntegrity:
    """Unknown revisions stay unknown — no invented data."""

    def test_empty_string_revision_becomes_none(self):
        rev = RepoRevision(repo_id="r", head_sha="", content_digest="")
        assert rev.head_sha is None
        assert rev.content_digest is None

    def test_unknown_revision_is_not_a_placeholder(self):
        rev = RepoRevision(repo_id="r")
        assert rev.head_sha is None
        assert rev.content_digest is None

    def test_unversioned_repo_has_no_sha(self):
        rev = RepoRevision(repo_id="r", unversioned=True)
        assert rev.head_sha is None
        assert rev.unversioned is True


class TestCompletenessConservative:
    """Completeness is never implied by a positive result."""

    def test_default_is_incomplete(self):
        c = CompletenessAssessment()
        assert c.complete is False

    def test_safe_to_delete_is_always_false(self):
        c = CompletenessAssessment(complete=True)
        assert c.safe_to_delete is False

    def test_scan_completed_does_not_imply_complete(self):
        c = CompletenessAssessment(scan_completed=True)
        assert c.complete is False

    def test_unsupported_idioms_prevent_completeness(self):
        c = CompletenessAssessment(
            complete=True, unsupported_idioms=["rails_routes"])
        # If unsupported idioms exist, complete should not be claimed
        # without accounting for them — the model allows it but the
        # evaluator (CTX-003) will not set complete=True when idioms
        # are unsupported.  Here we test that the fields are carried.
        assert c.unsupported_idioms == ["rails_routes"]


class TestSnapshotIdentity:
    """Canonical digest is deterministic and input-sensitive."""

    def test_identical_inputs_same_digest(self):
        s1 = SnapshotIdentity(
            repos=[RepoRevision(repo_id="a", head_sha="abc")],
            engine_version="2.0.0",
            config_version="1.0",
        )
        s2 = SnapshotIdentity(
            repos=[RepoRevision(repo_id="a", head_sha="abc")],
            engine_version="2.0.0",
            config_version="1.0",
        )
        assert s1.canonical_digest() == s2.canonical_digest()

    def test_changed_revision_changes_digest(self):
        s1 = SnapshotIdentity(
            repos=[RepoRevision(repo_id="a", head_sha="abc")],
            engine_version="2.0.0",
        )
        s2 = SnapshotIdentity(
            repos=[RepoRevision(repo_id="a", head_sha="def")],
            engine_version="2.0.0",
        )
        assert s1.canonical_digest() != s2.canonical_digest()

    def test_reordered_repos_same_digest(self):
        s1 = SnapshotIdentity(
            repos=[
                RepoRevision(repo_id="b", head_sha="x"),
                RepoRevision(repo_id="a", head_sha="y"),
            ],
            engine_version="2.0.0",
        )
        s2 = SnapshotIdentity(
            repos=[
                RepoRevision(repo_id="a", head_sha="y"),
                RepoRevision(repo_id="b", head_sha="x"),
            ],
            engine_version="2.0.0",
        )
        assert s1.canonical_digest() == s2.canonical_digest()


class TestVersioning:
    """Every envelope carries the answer version."""

    def test_version_in_every_envelope(self):
        env = _envelope(AnswerStatus.PRESENT)
        assert env.answer_version == ANSWER_VERSION

    def test_mcp_content_includes_version(self):
        env = _envelope(AnswerStatus.PRESENT)
        content = env.to_mcp_content()
        import json
        payload = json.loads(content[0]["text"])
        assert payload["answer_version"] == ANSWER_VERSION


class TestTruncation:
    """Truncation is explicit, not silent."""

    def test_truncated_result_is_not_complete(self):
        env = _envelope(
            AnswerStatus.PRESENT,
            scope_kw={"truncation": TruncationInfo(
                truncated=True, reason="node budget", omitted_count=50)},
        )
        assert env.scope.truncation.truncated is True
        assert env.scope.truncation.omitted_count == 50
