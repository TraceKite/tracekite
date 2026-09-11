"""The golden corpus: labelled ground truth, versioned in-repo.

Three tiny repositories that reproduce the join this tool exists for — a
Python call site, a Go route, a compose env var binding them — with the
expected edges written down by hand in `corpus/labels.yml`.

Source rather than captured artifacts on purpose: the precision gate this
feeds has to notice when an *extractor* change moves precision, and an
artifact freezes the extractor's output.

Runs with no database, no network and no ingested estate, so it can gate a
pull request.
"""

import os

import pytest
import yaml

from evigraph import engine_config
from evigraph.db.memory_store import InMemoryLinkerStore
from evigraph.services.linker.engine import link
from evigraph.services.scan import scan

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LABELS = os.path.join(ROOT, "corpus", "labels.yml")


@pytest.fixture(scope="module")
def corpus():
    with open(LABELS, encoding="utf-8") as fh:
        labels = yaml.safe_load(fh)
    engine_config.configure(graph_hmac_key="golden-corpus-key")
    sinks = [scan(os.path.join(ROOT, path), name)
             for name, path in labels["repos"].items()]
    result = link(InMemoryLinkerStore(sinks).load_claims(),
                  run_id="linkrun_corpus", now="2026-01-01T00:00:00+00:00")
    return labels, result


def _short(node_id: str) -> str:
    return node_id.split(":")[-1]


def _matches(edge, spec: dict) -> bool:
    if edge.type != spec["type"]:
        return False
    if "source_name" in spec and spec["source_name"] not in edge.source_id:
        return False
    if "target_name" in spec and spec["target_name"] not in edge.target_id:
        return False
    if "target_contains" in spec and spec["target_contains"] not in edge.target_id:
        return False
    return True


class TestGroundTruth:
    def test_the_corpus_is_in_the_repository(self):
        """No network, no database, no ingested estate — or it cannot gate a
        pull request."""
        assert os.path.isfile(LABELS)
        for path in yaml.safe_load(open(LABELS))["repos"].values():
            assert os.path.isdir(os.path.join(ROOT, path)), path

    def test_every_labelled_edge_is_produced(self, corpus):
        """Recall. A missing edge is a regression even when nothing is
        wrong — silence is what this project refuses."""
        labels, result = corpus
        active = [e for e in result.edges if e.status == "active"]
        missing = [spec for spec in labels["expect"]
                   if not any(_matches(e, spec) for e in active)]
        assert not missing, [s["type"] for s in missing]

    def test_each_one_meets_its_confidence_floor(self, corpus):
        labels, result = corpus
        active = [e for e in result.edges if e.status == "active"]
        for spec in labels["expect"]:
            hits = [e for e in active if _matches(e, spec)]
            assert hits, spec["type"]
            assert max(e.confidence for e in hits) >= spec["min_confidence"], (
                spec["type"], [e.confidence for e in hits])

    def test_each_one_cites_the_expected_file(self, corpus):
        """An edge with the right shape and the wrong provenance is not the
        same edge."""
        labels, result = corpus
        active = [e for e in result.edges if e.status == "active"]
        for spec in labels["expect"]:
            hits = [e for e in active if _matches(e, spec)]
            cited = {c.rsplit(":", 1)[0] for e in hits for c in e.evidence}
            assert any(spec["evidence"] in c for c in cited), (
                spec["type"], sorted(cited))

    def test_the_cross_repo_join_no_ast_could_make(self, corpus):
        """The flagship case, asserted on its own because it is the claim the
        whole project rests on: neither source file names the other."""
        _, result = corpus
        calls = [e for e in result.edges
                 if e.type == "CALLS_SERVICE" and e.status == "active"]
        assert calls, "the corpus must reproduce a cross-repo call"
        edge = calls[0]
        assert "orders-service" in edge.source_id
        assert "billing-service" in edge.target_id
        assert any("billing_client.py" in c for c in edge.evidence)

    def test_known_gaps_are_recorded_not_implied(self, corpus):
        """A corpus that lists only what works cannot show a recall
        improvement when one lands."""
        labels, _ = corpus
        assert labels.get("known_gaps"), "record what does not work yet"
        for gap in labels["known_gaps"]:
            assert gap.get("what") and gap.get("why_it_matters")


class TestScaleProbe:
    """The probe runs and reports the shape.

    Kept small here — the real measurement is run by hand at 100+ repos. What
    this pins is that the probe still works, so the numbers in architecture.md
    can be re-derived rather than trusted.
    """

    def test_the_probe_measures_phases_and_skew(self):
        import sys

        sys.path.insert(0, os.path.join(ROOT, "backend", "tools"))
        import scale_probe

        result = scale_probe.probe(4)
        assert result["repos"] == 12, "3 repos per corpus copy"
        assert result["claims"] > 0 and result["edges"] > 0
        assert {"map_s", "join_s", "map_share"} <= set(result)
        assert result["skew"]["keys"] > 0

    def test_map_dominates_not_the_join(self):
        """The finding that redirects B12: parallelising the join divides
        milliseconds. If this ever inverts, the parallel design should be
        revisited before more is built on it."""
        import sys

        sys.path.insert(0, os.path.join(ROOT, "backend", "tools"))
        import scale_probe

        result = scale_probe.probe(8)
        assert result["map_s"] > result["join_s"], (
            "the join overtook MAP — architecture.md's parallel plan assumes "
            "otherwise and should be re-measured")


class TestRecallGate:
    """A recall drop fails the build.

    The corpus asserts each labelled edge is produced. This adds the part a
    per-edge assertion misses: the *count*. A change that silently stops
    producing a whole class of edge passes every individual check that no
    longer runs, so the total is pinned too.

    Precision is gated separately, by `tools/calibrate.py`, which measures
    served edges per tier against the recorded rows — that is the mechanism
    that already exists, and duplicating it here would give two answers to
    one question.
    """

    def test_the_expected_edge_count_does_not_silently_fall(self, corpus):
        labels, result = corpus
        active = [e for e in result.edges if e.status == "active"]
        assert len(active) >= labels["min_active_edges"], (
            f"{len(active)} active edges, expected at least "
            f"{labels['min_active_edges']}. A drop here is a recall "
            "regression even when every labelled edge still resolves.")

    def test_no_labelled_edge_became_a_candidate(self, corpus):
        """Demotion below the floor is a recall loss that a shape check
        cannot see: the edge still exists, but nobody is served it."""
        labels, result = corpus
        for spec in labels["expect"]:
            hits = [e for e in result.edges if _matches(e, spec)]
            assert hits, spec["type"]
            assert any(e.status == "active" for e in hits), (
                f"{spec['type']} exists only as a candidate — it is no "
                "longer in any default answer")

    def test_the_cross_repo_join_is_never_merely_a_candidate(self, corpus):
        """The flagship edge specifically. If this demotes, the project's
        central claim stops being demonstrable."""
        _, result = corpus
        assert [e for e in result.edges
                if e.type == "CALLS_SERVICE" and e.status == "active"]
