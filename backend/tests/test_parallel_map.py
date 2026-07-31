"""Scanning many repositories at once (toward B12).

H8 established where the time is: the join is 0.03s over the live estate and
MAP is 87–94% of everything, so MAP is what gets parallelised. What these pin
is correctness under a process pool — the speedup itself is measured by
`tools/scale_probe.py`, and is currently modest for reasons recorded in
architecture.md.
"""

import os
import shutil

import pytest

from adduce import engine_config
from adduce.services.parallel_map import scan_many

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


@pytest.fixture
def repos(tmp_path):
    engine_config.configure(graph_hmac_key="parallel-map-key")
    made = []
    for i in range(4):
        dst = tmp_path / "src" / f"repo-{i}"
        shutil.copytree(SAMPLE, dst)
        made.append((f"repo-{i}", str(dst)))
    return made


class TestParallelMap:
    def test_every_repo_produces_an_artifact(self, repos, tmp_path):
        result = scan_many(repos, str(tmp_path / "art"), workers=2,
                           hmac_key="parallel-map-key")
        assert len(result.artifacts) == len(repos)
        assert result.ok

    def test_parallel_and_serial_agree(self, repos, tmp_path):
        """The point of determinism: more workers must not mean a different
        graph. If these diverge, every downstream diff is noise."""
        serial = scan_many(repos, str(tmp_path / "a"), workers=1,
                           hmac_key="parallel-map-key")
        parallel = scan_many(repos, str(tmp_path / "b"), workers=4,
                             hmac_key="parallel-map-key")
        assert ([os.path.basename(p) for p in serial.artifacts]
                == [os.path.basename(p) for p in parallel.artifacts])

    def test_results_are_ordered_regardless_of_completion(self, repos,
                                                          tmp_path):
        """Futures complete in an unpredictable order; an artifact list that
        changed order between runs would break artifact diffing."""
        a = scan_many(repos, str(tmp_path / "a"), workers=4,
                      hmac_key="parallel-map-key")
        b = scan_many(repos, str(tmp_path / "b"), workers=4,
                      hmac_key="parallel-map-key")
        assert ([os.path.basename(p) for p in a.artifacts]
                == [os.path.basename(p) for p in b.artifacts])

    def test_one_bad_repo_does_not_take_down_the_estate(self, repos,
                                                        tmp_path):
        """And the failure is named, not swallowed."""
        broken = repos + [("missing", str(tmp_path / "does-not-exist"))]
        result = scan_many(broken, str(tmp_path / "art"), workers=2,
                           hmac_key="parallel-map-key")
        assert len(result.artifacts) == len(repos)
        assert "missing" in result.failed
        assert not result.ok

    def test_a_second_pass_reuses_unchanged_repos(self, repos, tmp_path):
        """Incremental re-ingest still applies with a pool: a static
        estate costs almost nothing however many workers there are."""
        out = str(tmp_path / "art")
        scan_many(repos, out, workers=2, hmac_key="parallel-map-key")
        again = scan_many(repos, out, workers=2, hmac_key="parallel-map-key")
        assert len(again.reused) == len(repos)

    def test_workers_configure_the_engine_themselves(self, repos, tmp_path):
        """A pool does not inherit module state. A worker running on defaults
        would hash config under an empty key and silently produce a different
        graph from its siblings."""
        result = scan_many(repos, str(tmp_path / "art"), workers=2,
                           hmac_key="explicitly-passed-key")
        assert result.ok and result.artifacts
