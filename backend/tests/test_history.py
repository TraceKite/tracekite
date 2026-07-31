"""Validity ranges derived from the artifact series.

Architecture §3.4 rules out storing time on the edge, so the range is computed
from a series of commits. The failure this file exists to prevent is a range
that looks continuous over a period the edge was absent — an invented edge
wearing a timestamp, and harder to spot than an invented edge, because nobody
checks a date twice.
"""

import os

from adduce import engine_config
from adduce.db.artifact import write_artifact
from adduce.db.artifact_reader import read_artifact
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.models.graph_models import GraphEdge
from adduce.services.linker.history import (
    changed_between, consumers_over_time, edge_history, edge_key,
)
from adduce.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


def edge(source, target, status="active", evidence=("a.py:1",),
         confidence=0.9):
    e = GraphEdge(source_id=source, target_id=target, repo_id="r",
                  type="CALLS_SERVICE", evidence=list(evidence),
                  detected_by="resolver.test@1")
    e.status = status
    e.confidence = confidence
    return e


class TestIntervals:
    def test_an_edge_present_throughout_has_one_interval(self):
        history = edge_history([
            ("sha1", [edge("a", "b")]),
            ("sha2", [edge("a", "b")]),
            ("sha3", [edge("a", "b")]),
        ])
        assert len(history) == 1
        assert len(history[0].intervals) == 1
        assert history[0].intervals[0].first_commit == "sha1"
        assert history[0].intervals[0].last_commit == "sha3"
        assert history[0].present_at_head is True

    def test_an_edge_that_went_away_is_not_present_at_head(self):
        history = edge_history([
            ("sha1", [edge("a", "b")]),
            ("sha2", []),
        ])
        assert history[0].intervals[0].last_commit == "sha1"
        assert history[0].present_at_head is False

    def test_an_edge_that_came_back_gets_two_intervals(self):
        """The one that matters. Collapsing these into sha1..sha3 would assert
        the edge existed at sha2, where it did not."""
        history = edge_history([
            ("sha1", [edge("a", "b")]),
            ("sha2", []),
            ("sha3", [edge("a", "b")]),
        ])
        assert len(history[0].intervals) == 2
        assert history[0].reappeared is True
        assert [(i.first_commit, i.last_commit) for i in history[0].intervals] \
            == [("sha1", "sha1"), ("sha3", "sha3")]
        assert history[0].present_at_head is True

    def test_a_candidate_edge_is_not_counted_as_present(self):
        """Candidates are excluded from default answers, so reporting one as
        present claims a connection the tool would not have shown."""
        history = edge_history([
            ("sha1", [edge("a", "b", status="candidate")]),
            ("sha2", [edge("a", "b")]),
        ])
        assert history[0].intervals[0].first_commit == "sha2"

    def test_dropping_to_candidate_ends_the_interval(self):
        history = edge_history([
            ("sha1", [edge("a", "b")]),
            ("sha2", [edge("a", "b", status="candidate")]),
        ])
        assert history[0].intervals[0].last_commit == "sha1"
        assert history[0].present_at_head is False

    def test_an_empty_series_reports_nothing_rather_than_failing(self):
        assert edge_history([]) == []

    def test_output_is_ordered_so_two_runs_can_be_compared(self):
        history = edge_history([("sha1", [edge("z", "y"), edge("a", "b")])])
        assert [(h.source, h.target) for h in history] == [("a", "b"),
                                                           ("z", "y")]


class TestEdgeIdentity:
    def test_evidence_and_confidence_are_not_identity(self):
        """Line numbers move when a file is edited above the call site, and
        confidence changes when a resolver is retuned. Either as identity
        would report the edge removed and re-added on every unrelated
        commit."""
        assert edge_key(edge("a", "b", evidence=("a.py:1",), confidence=0.9)) \
            == edge_key(edge("a", "b", evidence=("a.py:40",), confidence=0.7))

    def test_a_moved_call_site_does_not_look_like_a_change(self):
        history = edge_history([
            ("sha1", [edge("a", "b", evidence=("client.py:14",))]),
            ("sha2", [edge("a", "b", evidence=("client.py:31",))]),
        ])
        assert len(history) == 1 and len(history[0].intervals) == 1

    def test_the_edge_type_is_part_of_identity(self):
        other = edge("a", "b")
        other.type = "ROUTES_TO"
        assert len(edge_history([("sha1", [edge("a", "b"), other])])) == 2


class TestChangedBetween:
    def test_added_removed_and_kept(self):
        result = changed_between(
            before=[edge("a", "b"), edge("c", "d")],
            after=[edge("c", "d"), edge("e", "f")])
        assert [e.target_id for e in result["added"]] == ["f"]
        assert [e.target_id for e in result["removed"]] == ["b"]
        assert [e.target_id for e in result["kept"]] == ["d"]

    def test_a_candidate_is_neither_added_nor_kept(self):
        result = changed_between(
            before=[], after=[edge("a", "b", status="candidate")])
        assert result["added"] == [] and result["kept"] == []


class TestArtifactRoundTrip:
    """History over real artifacts, not just constructed edges.

    `read_artifact` is new, and if it returned nodes the linker cannot read,
    every history report would be empty and every interval correct.
    """

    def test_an_artifact_relinks_to_the_same_edges(self, tmp_path):
        engine_config.configure(graph_hmac_key="history-test-key")
        sink = scan(SAMPLE, "repo_a")
        ref = write_artifact(sink, "repo_a", str(tmp_path), head_sha="deadbee")

        contents = read_artifact(ref.path)
        assert contents.head_sha == "deadbee"
        assert len(contents.nodes) == len(sink.nodes)

        from_scan = InMemoryLinkerStore([sink]).load_claims()
        from_artifact = InMemoryLinkerStore([contents]).load_claims()
        assert {c.id for c in from_artifact} == {c.id for c in from_scan}
        assert {c.key for c in from_artifact} == {c.key for c in from_scan}

    def test_an_artifact_with_no_commit_says_so(self, tmp_path):
        """Empty rather than a guess: inventing a sha would anchor a temporal
        answer to a commit that never existed."""
        engine_config.configure(graph_hmac_key="history-test-key")
        ref = write_artifact(scan(SAMPLE, "repo_a"), "repo_a", str(tmp_path))
        assert read_artifact(ref.path).head_sha == ""


class TestConsumersOverTime:
    def test_the_consumer_set_is_reported_per_commit(self):
        report = consumers_over_time([
            ("sha1", [edge("a", "t"), edge("b", "t")]),
            ("sha2", [edge("b", "t")]),
        ], "t")
        assert report["found"] is True
        assert [e["consumers"] for e in report["history"]] == [
            ["a", "b"], ["b"]]
        assert report["current_consumers"] == ["b"]
        # Who already migrated away — the difference that shows progress.
        assert report["former_consumers"] == ["a"]

    def test_an_unknown_target_returns_candidates_not_an_empty_history(self):
        """Empty would read as "measured, and nobody depends on it" — the
        one wrong answer to hand someone deciding whether a removal is
        safe."""
        report = consumers_over_time([("sha1", [edge("a", "t")])], "typo")
        assert report["found"] is False
        assert report["history"] == []
        assert report["candidates"] == ["t"]

    def test_a_candidate_only_target_is_not_found(self):
        """A target that exists only as candidate edges was never served,
        so reporting a consumer history for it would be a history of
        assertions the tool declined to make."""
        report = consumers_over_time(
            [("sha1", [edge("a", "t", status="candidate")])], "t")
        assert report["found"] is False
        assert report["candidates"] == []
