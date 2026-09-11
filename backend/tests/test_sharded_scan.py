"""A sharded scan is the serial scan, faster.

The whole contract is one sentence: same repository, same bytes, any worker
count. Artifacts are content-addressed, so the test compares digests — a
reordered node, a double-counted coverage field or a dropped claim all
surface as a different hash, which is the strongest equivalence a test can
assert and the only one B7's reuse and the diffing actually depend on.
"""

import os
import sys

from tracekite import engine_config
from tracekite.db.artifact import write_artifact
from tracekite.services.scan import scan
from tracekite.services.sharded_scan import scan_sharded
from tracekite.services.sink_merge import merge_chunk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from tools.synth_estate import generate  # noqa: E402

KEY = "sharded-scan-test"


def monorepo(tmp_path) -> str:
    generate(str(tmp_path / "estate"), repos=0, monorepos=1, mono_services=6,
             calls_per_service=1, pad_files=35, pad_functions=2, seed=13)
    repo = str(tmp_path / "estate" / "mono-0000")
    # Guard the guard: at 6 services x 33 files this fixture once sat UNDER
    # the shard threshold, so the digest test compared the serial fallback
    # with itself and proved nothing. If the threshold or the generator
    # moves, fail here rather than pass vacuously.
    from tracekite.services.file_scanner import scan_repository
    from tracekite.services.sharded_scan import SHARD_THRESHOLD_FILES

    found = len(scan_repository(repo).files)
    assert found >= SHARD_THRESHOLD_FILES, (
        f"fixture has {found} files, under the {SHARD_THRESHOLD_FILES} "
        "shard threshold — the equivalence tests would test nothing")
    return repo


class TestByteEquivalence:
    def test_sharded_scan_produces_the_serial_artifact(self, tmp_path):
        """Digest equality over a monorepo big enough to actually shard
        (6 services, ~200 files), with chunks small enough that the merge
        happens many times rather than once."""
        repo = monorepo(tmp_path)
        engine_config.configure(graph_hmac_key=KEY)

        serial = write_artifact(scan(repo, "mono", head_sha="abc"),
                                "mono", str(tmp_path / "a"), head_sha="abc")
        sink = scan_sharded(repo, "mono", workers=3, hmac_key=KEY,
                            head_sha="abc", chunk_files=16)
        sharded = write_artifact(sink, "mono", str(tmp_path / "b"),
                                 head_sha="abc")

        assert serial.nodes and serial.edges
        assert sharded.digest == serial.digest

    def test_below_the_threshold_it_is_literally_the_serial_scan(
            self, tmp_path, monkeypatch):
        from tracekite.services import sharded_scan as module

        repo = monorepo(tmp_path)
        engine_config.configure(graph_hmac_key=KEY)
        monkeypatch.setattr(module, "SHARD_THRESHOLD_FILES", 10_000)

        serial = write_artifact(scan(repo, "mono"), "mono",
                                str(tmp_path / "a"))
        small = write_artifact(
            scan_sharded(repo, "mono", workers=3, hmac_key=KEY),
            "mono", str(tmp_path / "b"))
        assert small.digest == serial.digest

    def test_a_capped_repo_falls_back_and_matches_the_serial_cap(
            self, tmp_path, caplog):
        """The serial loop stops before the file that would exceed the
        claim cap; chunks cannot see that coming. The sharded path must
        detect the cap at merge, re-run serially, and produce the capped
        artifact — not a differently-truncated one."""
        repo = monorepo(tmp_path)
        engine_config.configure(graph_hmac_key=KEY, max_claims_per_repo=5)
        try:
            serial = write_artifact(scan(repo, "mono"), "mono",
                                    str(tmp_path / "a"))
            sink = scan_sharded(repo, "mono", workers=3, hmac_key=KEY,
                                chunk_files=16)
            sharded = write_artifact(sink, "mono", str(tmp_path / "b"))
        finally:
            # configure() layers values over the ACTIVE config, so calling
            # it again does not undo the cap — the first version of this
            # restore leaked max_claims=5 into every scan the rest of the
            # suite ran, and the synthetic-estate test failed two files
            # away. Restoring means reset(), then configuring what you need.
            engine_config.reset()
            engine_config.configure(graph_hmac_key=KEY)

        assert sharded.digest == serial.digest
        assert any("cap fidelity" in r.getMessage() for r in caplog.records)


class TestMergeChunk:
    def test_coverage_sums_and_tier_upgrades(self):
        from tracekite.services.ingest_source import IngestSink

        target, chunk = IngestSink(), IngestSink()
        target.lang("Python")["files_parsed"] = 2
        target.upgrade_tier("Python", "lite")
        chunk.lang("Python")["files_parsed"] = 3
        chunk.upgrade_tier("Python", "full")
        chunk.count_claim("http")

        merge_chunk(target, chunk)
        assert target.coverage["Python"]["files_parsed"] == 5
        assert target.coverage["Python"]["tier"] == "full"
        assert target.claims == {"http": 1}

    def test_a_node_minted_by_two_chunks_collapses(self):
        from tracekite.models.graph_models import GraphNode
        from tracekite.services.ingest_source import IngestSink

        def node():
            return GraphNode(id="n1", repo_id="r", type="File",
                             label="File", name="f")

        target, a, b = IngestSink(), IngestSink(), IngestSink()
        a.add_node(node())
        b.add_node(node())
        merge_chunk(target, a)
        merge_chunk(target, b)
        assert len(target.nodes) == 1
