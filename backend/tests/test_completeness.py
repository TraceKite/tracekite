"""Tests for the conservative completeness evaluator."""

from tracekite.completeness import evaluate_completeness


class TestCompleteness:
    def test_all_factors_present_is_complete(self):
        c = evaluate_completeness(
            expected_repos=["a", "b"],
            analyzed_repos=["a", "b"],
            scan_completed=True,
        )
        assert c.complete is True
        assert c.coverage_reasons == []

    def test_missing_repo_prevents_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a", "b", "c"],
            analyzed_repos=["a", "b"],
            scan_completed=True,
        )
        assert c.complete is False
        assert "c" in c.coverage_reasons
        assert c.missing_repos == ["c"]

    def test_parse_failures_prevent_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
            parse_failures=5,
        )
        assert c.complete is False
        assert any("parse" in r for r in c.coverage_reasons)

    def test_unsupported_idioms_prevent_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
            unsupported_idioms=["rails_routes"],
        )
        assert c.complete is False
        assert "rails_routes" in str(c.coverage_reasons)

    def test_truncation_prevents_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
            result_truncated=True,
        )
        assert c.complete is False
        assert any("truncat" in r for r in c.coverage_reasons)

    def test_scan_coverage_reasons_are_preserved(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
            coverage_reasons=["a: unsupported configuration idiom"],
        )
        assert c.complete is False
        assert c.coverage_reasons == ["a: unsupported configuration idiom"]

    def test_unresolved_matching_prevents_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
            unresolved_matching=3,
        )
        assert c.complete is False
        assert any("unresolved" in r for r in c.coverage_reasons)

    def test_scan_not_completed_prevents_completeness(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=False,
        )
        assert c.complete is False

    def test_safe_to_delete_is_always_false(self):
        c = evaluate_completeness(
            expected_repos=["a"],
            analyzed_repos=["a"],
            scan_completed=True,
        )
        assert c.complete is True
        assert c.safe_to_delete is False
