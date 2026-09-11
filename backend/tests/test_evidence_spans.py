"""F4: spans are derived from evidence strings, never stored (§3.1 wins).

The two properties that matter: the span reading never invents a line a
string does not carry, and the identity-critical path reading never moves
— claim ids hash it, so a change there churns every id in every stored
artifact. The identity tests below compute the expected id with the
historical inline formula and assert the module reproduces it exactly.
"""

from tracekite.services.claims import ContractClaim
from tracekite.utils.evidence import (
    EvidenceSpan, as_spans, evidence_path, format_evidence, parse_evidence,
)


class TestGrammar:
    def test_single_line(self):
        span = parse_evidence("src/app/api.py:42")
        assert span == EvidenceSpan("src/app/api.py", 42, 42)

    def test_range(self):
        span = parse_evidence("src/app/api.py:42-45")
        assert span == EvidenceSpan("src/app/api.py", 42, 45)

    def test_no_line(self):
        assert parse_evidence("Dockerfile") == EvidenceSpan("Dockerfile")

    def test_never_invents_a_line(self):
        # A tail that is not a number belongs to the file name; a reversed
        # range is malformed. Both are files, not locations.
        assert parse_evidence("a.py:notaline") == \
            EvidenceSpan("a.py:notaline")
        assert parse_evidence("a.py:45-42") == EvidenceSpan("a.py:45-42")

    def test_round_trips(self):
        for text in ("a/b.py:7", "a/b.py:7-9", "Dockerfile"):
            assert format_evidence(parse_evidence(text)) == text

    def test_as_spans_carries_commit_only_when_given(self):
        [with_commit] = as_spans(["a.py:3"], commit="abc123")
        assert with_commit == {"file": "a.py", "line_start": 3,
                               "line_end": 3, "commit": "abc123"}
        [without] = as_spans(["a.py:3"])
        assert "commit" not in without


class TestIdentityFrozen:
    """evidence_path must forever match the rsplit claim ids hashed."""

    CASES = ("src/main/app.py:42", "Dockerfile", "weird:tail",
             "a/b.py:42-45", "a:b/c.py:7")

    def test_path_semantics_are_the_historical_rsplit(self):
        for evidence in self.CASES:
            assert evidence_path(evidence) == evidence.rsplit(":", 1)[0]

    def test_claim_ids_do_not_churn(self):
        import hashlib

        for evidence in self.CASES:
            claim = ContractClaim(
                repo_id="repo_a", kind="http", direction="provides",
                key="GET:/v1/x", evidence=[evidence])
            historical = ("repo_a:ContractClaim:" + hashlib.sha256(
                f"http:provides:GET:/v1/x:{evidence.rsplit(':', 1)[0]}:"
                .encode()).hexdigest()[:16])
            assert claim.id == historical, evidence
