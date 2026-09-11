"""Claims stream out of artifacts without the graph coming with them.

The 1,001-repo measurement put the artifacts' claims at ~2% of their rows;
the other 98% cost 2.9 of a 5.8-second repush and were discarded unread.
`read_claims` selects the 2% in SQL. Two ways that can go wrong, one per
test class: the streamed claims could differ from the round trip everything
else uses, and the memory could quietly stay proportional to the graph.
"""

import os
import tracemalloc

from evigraph import engine_config
from evigraph.db.artifact import write_artifact
from evigraph.db.artifact_reader import read_artifact, read_claims
from evigraph.db.memory_store import claims_from_scan
from evigraph.services.linker.engine import link
from evigraph.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


def artifact_for(tmp_path, repo_path=SAMPLE, repo_id="repo_a"):
    engine_config.configure(graph_hmac_key="streaming-claims-test")
    sink = scan(repo_path, repo_id)
    return sink, write_artifact(sink, repo_id, str(tmp_path)).path


class TestEquivalence:
    def test_streamed_claims_match_the_scan_round_trip(self, tmp_path):
        """Field for field. The two readers share `claim_record`, so what
        this actually pins is the SQL — a wrong join or a missed payload
        field shows up here as a differing claim, not as quietly worse
        recall three layers up."""
        sink, path = artifact_for(tmp_path)
        from_sink = {c.id: c for c in claims_from_scan(sink)}
        streamed = {c.id: c for c in read_claims(path)}

        assert streamed.keys() == from_sink.keys()
        assert from_sink, "fixture produced no claims; nothing was tested"
        for cid, expected in from_sink.items():
            assert streamed[cid] == expected, cid

    def test_the_link_agrees_with_the_full_reader(self, tmp_path):
        """Same edges, same counters, whichever reader loaded the claims."""
        _sink, path = artifact_for(tmp_path)

        def run(claims):
            return link(claims, run_id="linkrun_stream",
                        now="2026-01-01T00:00:00+00:00")

        from evigraph.db.memory_store import InMemoryLinkerStore
        full = run(InMemoryLinkerStore([read_artifact(path)]).load_claims())
        streamed = run(read_claims(path))

        assert streamed.counters == full.counters
        assert ([(e.type, e.source_id, e.target_id) for e in streamed.edges]
                == [(e.type, e.source_id, e.target_id) for e in full.edges])

    def test_an_artifact_with_no_claims_streams_empty_not_broken(
            self, tmp_path):
        sink, path = artifact_for(tmp_path)
        # Rewrite with the claims filtered out of the same graph.
        sink.nodes = [n for n in sink.nodes if n.type != "ContractClaim"]
        bare = write_artifact(sink, "repo_bare", str(tmp_path)).path
        assert read_claims(bare) == []


class TestBoundedMemory:
    def test_reading_claims_does_not_pay_for_the_graph(self, tmp_path):
        """The exit criterion, at test scale: grow the *graph* while holding
        the claim count still, and the streaming reader's allocations must
        not grow with it. The full reader's do — that is what it is for —
        and measuring both in one test is what keeps this from passing
        vacuously on a fixture too small to show anything."""
        import shutil

        small = tmp_path / "small"
        shutil.copytree(SAMPLE, small)
        big = tmp_path / "big"
        shutil.copytree(SAMPLE, big)
        for index in range(120):
            (big / f"pad_{index:03d}.py").write_text(
                "\n".join(f"def fn_{index}_{n}():\n    return {n}"
                          for n in range(30)))

        # One repo id for both trees: claim ids embed it, and the point
        # is the same claims against a bigger graph, not two estates.
        _s, small_path = artifact_for(tmp_path / "a", str(small), "repo_x")
        _b, big_path = artifact_for(tmp_path / "b", str(big), "repo_x")

        def peak(fn, *args) -> int:
            tracemalloc.start()
            fn(*args)
            _current, peaked = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return peaked

        # Same claims either way — the padding parses but asserts nothing.
        assert {c.id for c in read_claims(big_path)} \
            == {c.id for c in read_claims(small_path)}

        full_growth = peak(read_artifact, big_path) \
            / max(peak(read_artifact, small_path), 1)
        stream_growth = peak(read_claims, big_path) \
            / max(peak(read_claims, small_path), 1)

        assert full_growth > 3, (
            f"padding grew the graph only {full_growth:.1f}x — the fixture "
            "is too small for this test to mean anything")
        assert stream_growth < 1.5, (
            f"streamed reads grew {stream_growth:.1f}x with graph size at "
            "constant claim count: the reader is paying for the graph")
