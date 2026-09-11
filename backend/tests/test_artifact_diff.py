"""What a change did to the graph.

A resolver diff says what the code now does, not what the graph now says.
This answers the second question — and it is only possible because artifacts
are byte-reproducible: without that, two runs of unchanged code would differ
and a real change would be indistinguishable from noise.
"""

import os
import shutil

import pytest

from tracekite import engine_config
from tracekite.db.artifact import write_artifact
from tracekite.db.artifact_diff import diff_artifacts
from tracekite.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


@pytest.fixture
def repo(tmp_path):
    engine_config.configure(graph_hmac_key="diff-test-key")
    work = tmp_path / "repo"
    shutil.copytree(SAMPLE, work)
    return work


def _artifact(repo, tmp_path, tag):
    return write_artifact(scan(str(repo), "r"), "r",
                          str(tmp_path / tag)).path


class TestDiff:
    def test_unchanged_source_shows_no_change(self, repo, tmp_path):
        """If this ever fails, artifact determinism has regressed and every
        diff below is noise."""
        a = _artifact(repo, tmp_path, "a")
        b = _artifact(repo, tmp_path, "b")
        diff = diff_artifacts(a, b)
        assert not diff.edges.changed
        assert diff.summary() == "no change to the graph"

    def test_a_new_call_site_appears_as_added_edges(self, repo, tmp_path):
        before = _artifact(repo, tmp_path, "a")
        (repo / "svc.py").write_text(
            'import httpx\ndef f():\n    return httpx.get("http://b/v1/x")\n')
        after = _artifact(repo, tmp_path, "b")

        diff = diff_artifacts(before, after)
        assert diff.edges.added and not diff.edges.removed
        assert diff.nodes_added > 0

    def test_removal_is_reported_separately_from_addition(self, repo,
                                                          tmp_path):
        """'+27 edges' and '-27 edges' are very different reviews; a net
        number would hide which happened."""
        before = _artifact(repo, tmp_path, "a")
        for name in os.listdir(repo):
            target = repo / name
            if target.is_file():
                target.unlink()
        after = _artifact(repo, tmp_path, "b")

        diff = diff_artifacts(before, after)
        assert diff.edges.removed and not diff.edges.added
        assert "-" in diff.summary()

    def test_the_summary_names_direction(self, repo, tmp_path):
        before = _artifact(repo, tmp_path, "a")
        (repo / "svc.py").write_text("import os\n")
        after = _artifact(repo, tmp_path, "b")
        assert "+" in diff_artifacts(before, after).summary()

    def test_counts_by_edge_type(self, repo, tmp_path):
        before = _artifact(repo, tmp_path, "a")
        (repo / "svc.py").write_text("import os\n")
        after = _artifact(repo, tmp_path, "b")
        by_type = diff_artifacts(before, after).by_type
        assert by_type and all(
            set(v) == {"added", "removed"} for v in by_type.values())

    def test_examples_are_capped_but_counts_are_not(self, repo, tmp_path):
        """A reviewer needs the true magnitude even when only the first few
        are shown; a truncated count would understate a regression."""
        before = _artifact(repo, tmp_path, "a")
        (repo / "svc.py").write_text("import os\n")
        after = _artifact(repo, tmp_path, "b")
        diff = diff_artifacts(before, after, limit=1)
        assert len(diff.edges.added) <= 1
        assert sum(v["added"] for v in diff.by_type.values()) >= 1

    def test_the_report_serialises(self, repo, tmp_path):
        a = _artifact(repo, tmp_path, "a")
        payload = diff_artifacts(a, a).as_dict()
        assert payload["summary"] == "no change to the graph"
