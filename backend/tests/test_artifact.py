"""A repo artifact is a single self-contained file.

Content addressing is what makes incremental re-ingest possible: "did this
repo change?" becomes a filename comparison rather than a diff. That only
works if the same repository really does produce the same bytes, so
determinism is tested here, not assumed from B6.
"""

import os

import pytest

from adduce import engine_config
from adduce.db.artifact import (
    ARTIFACT_SUFFIX, digest_of, is_unchanged, open_artifact, read_meta,
    write_artifact,
)
from adduce.db.graph_store import Aggregate
from adduce.services.scan import scan

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE = os.path.join(FIXTURES, "callgraph-sample")


@pytest.fixture(scope="module")
def scanned():
    engine_config.configure(graph_hmac_key="artifact-test-key")
    return scan(SAMPLE, "repo_a", owner="o", repo_name="callgraph-sample")


class TestSelfContained:
    def test_one_repo_becomes_one_file(self, scanned, tmp_path):
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        assert os.path.isfile(ref.path)
        assert ref.path.endswith(ARTIFACT_SUFFIX)
        assert len(os.listdir(tmp_path)) == 1, "one repo, one file"

    def test_the_artifact_is_queryable_without_the_repository(self, scanned,
                                                              tmp_path):
        """It is the database, not a dump that needs importing."""
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        store = open_artifact(ref.path)
        assert store.query(Aggregate("node")).rows[0]["count"] == ref.nodes
        assert store.query(Aggregate("edge")).rows[0]["count"] == ref.edges
        store.close()

    def test_metadata_reads_without_loading_the_graph(self, scanned, tmp_path):
        ref = write_artifact(scanned, "repo_a", str(tmp_path),
                             head_sha="cafe1234")
        meta = read_meta(ref.path)
        assert meta["repo_id"] == "repo_a"
        assert meta["head_sha"] == "cafe1234"
        assert meta["wire_version"].count(".") == 2
        assert meta["claims"], "an artifact with no claims proves nothing"

    def test_incompleteness_travels_with_the_artifact(self, scanned, tmp_path):
        """A scan that hit a cap or skipped an unfetched submodule is
        incomplete. An artifact that dropped that would read as a complete
        scan of a smaller repository — the silent truncation this codebase
        keeps refusing."""
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        meta = read_meta(ref.path)
        assert "capped" in meta and "unfetched_submodules" in meta


class TestContentAddressed:
    def test_the_name_carries_the_digest(self, scanned, tmp_path):
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        assert ref.digest[:16] in os.path.basename(ref.path)

    def test_the_same_scan_produces_the_same_bytes(self, scanned, tmp_path):
        a = write_artifact(scanned, "repo_a", str(tmp_path / "one"))
        b = write_artifact(scanned, "repo_a", str(tmp_path / "two"))
        assert a.digest == b.digest
        assert os.path.basename(a.path) == os.path.basename(b.path)

    def test_a_rescan_of_unchanged_source_matches(self, tmp_path):
        """The claim incremental re-ingest rests on: scanning the same tree
        twice must be indistinguishable, or nothing can ever be skipped."""
        engine_config.configure(graph_hmac_key="artifact-test-key")
        first = write_artifact(scan(SAMPLE, "repo_a"), "repo_a",
                               str(tmp_path / "a"))
        second = write_artifact(scan(SAMPLE, "repo_a"), "repo_a",
                                str(tmp_path / "b"))
        assert first.digest == second.digest

    def test_different_content_produces_a_different_digest(self, scanned,
                                                           tmp_path):
        """Guard the guard: if the digest were constant, every assertion
        above would pass while proving nothing."""
        engine_config.configure(graph_hmac_key="artifact-test-key")
        other = scan(os.path.join(FIXTURES, "planted-secret"), "repo_b")
        a = write_artifact(scanned, "repo_a", str(tmp_path / "a"))
        b = write_artifact(other, "repo_b", str(tmp_path / "b"))
        assert a.digest != b.digest

    def test_is_unchanged_answers_the_reingest_question(self, scanned,
                                                        tmp_path):
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        assert is_unchanged(ref.path, ref.digest) is True
        assert is_unchanged(ref.path, "0" * 64) is False
        assert is_unchanged(ref.path, "") is False

    def test_digest_covers_the_file_that_landed(self, scanned, tmp_path):
        ref = write_artifact(scanned, "repo_a", str(tmp_path))
        assert digest_of(ref.path) == ref.digest


class TestIncrementalReingest:
    """An unchanged repo costs ~zero on re-scan."""

    def test_first_pass_scans_and_writes(self, tmp_path):
        engine_config.configure(graph_hmac_key="artifact-test-key")
        from adduce.services.reingest import scan_if_changed

        ref, reused = scan_if_changed(SAMPLE, "repo_a", str(tmp_path))
        assert reused is False
        assert ref and os.path.isfile(ref.path)

    def test_second_pass_reuses_without_parsing(self, tmp_path):
        """The saving is the whole scan, not merely the write."""
        engine_config.configure(graph_hmac_key="artifact-test-key")
        from adduce.services.reingest import scan_if_changed

        first, _ = scan_if_changed(SAMPLE, "repo_a", str(tmp_path))
        second, reused = scan_if_changed(SAMPLE, "repo_a", str(tmp_path))
        assert reused is True
        assert second.path == first.path
        assert second.nodes == first.nodes and second.edges == first.edges

    def test_a_changed_file_forces_a_rescan(self, tmp_path):
        """Guard the guard: a fingerprint that never changed would make every
        re-scan look free while serving a stale graph forever."""
        import shutil

        engine_config.configure(graph_hmac_key="artifact-test-key")
        from adduce.services.reingest import scan_if_changed

        work = tmp_path / "repo"
        shutil.copytree(SAMPLE, work)
        out = str(tmp_path / "artifacts")

        _, first_reused = scan_if_changed(str(work), "repo_a", out)
        assert first_reused is False
        _, cached = scan_if_changed(str(work), "repo_a", out)
        assert cached is True

        (work / "newfile.py").write_text("import os\n")
        _, after_change = scan_if_changed(str(work), "repo_a", out)
        assert after_change is False, "a new file must invalidate the cache"

    def test_fingerprint_is_stable_and_content_sensitive(self, tmp_path):
        import shutil

        from adduce.services.reingest import source_fingerprint

        work = tmp_path / "repo"
        shutil.copytree(SAMPLE, work)
        before = source_fingerprint(str(work))
        assert source_fingerprint(str(work)) == before, "must be stable"

        (work / "extra.py").write_text("x = 1\n")
        assert source_fingerprint(str(work)) != before


class TestCompaction:
    """N artifacts merge into one queryable index."""

    def _artifacts(self, tmp_path, count):
        engine_config.configure(graph_hmac_key="artifact-test-key")
        sample = scan(SAMPLE, "base")
        out = tmp_path / "arts"
        return [write_artifact(sample, f"repo_{i}", str(out)).path
                for i in range(count)]

    def test_many_artifacts_become_one_index(self, tmp_path):
        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 12)
        result = compact(paths, str(tmp_path / "index.db"))
        assert result.artifacts == 12
        assert len(result.repos) == 12
        assert result.nodes > 0 and result.edges > 0

    def test_the_index_is_queryable(self, tmp_path):
        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 5)
        result = compact(paths, str(tmp_path / "index.db"))
        store = open_artifact(result.path)
        assert store.query(Aggregate("node")).rows[0]["count"] == result.nodes
        store.close()

    def test_recompacting_supersedes_rather_than_duplicates(self, tmp_path):
        """An artifact merged twice must not double its rows — identity is
        the node id, not the number of times it arrived."""
        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 3)
        once = compact(paths, str(tmp_path / "a.db"))
        twice = compact(paths + paths, str(tmp_path / "b.db"))
        assert twice.nodes == once.nodes
        assert twice.edges == once.edges

    def test_an_unreadable_artifact_is_named_not_dropped(self, tmp_path):
        """A compaction that quietly omitted a repo would produce an index
        that looks complete and is missing an estate's worth of edges."""
        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 2)
        broken = tmp_path / "broken.adduce"
        broken.write_bytes(b"not a database at all")
        result = compact(paths + [str(broken)], str(tmp_path / "index.db"))
        assert result.artifacts == 2
        assert "broken.adduce" in result.skipped

    def test_a_wrong_wire_version_is_refused_and_reported(self, tmp_path):
        """Merging an artifact written against a different contract would
        silently mix two shapes."""
        import sqlite3 as sq

        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 1)
        stale = tmp_path / "arts" / "stale.adduce"
        stale.write_bytes(open(paths[0], "rb").read())
        conn = sq.connect(str(stale))
        conn.execute("UPDATE artifact_meta SET value='0.0.1' "
                     "WHERE key='wire_version'")
        conn.commit()
        conn.close()

        result = compact(paths + [str(stale)], str(tmp_path / "index.db"))
        assert result.artifacts == 1
        assert "wire" in result.skipped["stale.adduce"]

    def test_the_index_records_what_it_contains(self, tmp_path):
        from adduce.db.artifact import compact

        paths = self._artifacts(tmp_path, 4)
        result = compact(paths, str(tmp_path / "index.db"))
        meta = read_meta(result.path)
        assert meta["kind"] == "compacted-index"
        assert sorted(meta["repos"]) == result.repos


class TestAbsenceIsRecorded:
    """"Looked and found nothing" is not the same as "could not look"."""

    def test_a_clean_scan_says_its_absence_is_evidence(self, tmp_path):
        engine_config.configure(graph_hmac_key="artifact-test-key")
        sink = scan(SAMPLE, "repo_a")
        assert sink.absence["complete"] is True
        assert sink.absence["absence_is_evidence"] is True
        assert sink.absence["kinds_absent"], "nothing was found to be absent"

    def test_kinds_found_and_absent_are_disjoint(self, tmp_path):
        engine_config.configure(graph_hmac_key="artifact-test-key")
        a = scan(SAMPLE, "repo_a").absence
        assert not (set(a["kinds_found"]) & set(a["kinds_absent"]))

    def test_a_capped_scan_refuses_to_call_absence_evidence(self, tmp_path):
        """A truncated scan cannot claim anything about what it never
        reached — that is the implied absence C5 removes."""
        import dataclasses

        from adduce import engine_config as ec

        original = ec._active
        try:
            ec._active = dataclasses.replace(
                ec.get_config(), graph_hmac_key="k", max_files_per_repo=1)
            sink = scan(SAMPLE, "repo_a")
        finally:
            ec._active = original
        assert sink.absence["complete"] is False
        assert sink.absence["absence_is_evidence"] is False
        assert any("cap" in r for r in sink.absence["incomplete_because"])

    def test_the_reasons_are_specific_not_a_flag(self, tmp_path):
        """A reviewer deciding whether to trust an absence needs to know it
        was a parse error in Kotlin, not a size cap in YAML — those suggest
        different follow-ups."""
        import dataclasses

        from adduce import engine_config as ec

        original = ec._active
        try:
            ec._active = dataclasses.replace(
                ec.get_config(), graph_hmac_key="k", parse_file_cap_bytes=10)
            sink = scan(SAMPLE, "repo_a")
        finally:
            ec._active = original
        assert any("size cap" in r for r in sink.absence["incomplete_because"])

    def test_absence_travels_with_the_artifact(self, tmp_path):
        engine_config.configure(graph_hmac_key="artifact-test-key")
        ref = write_artifact(scan(SAMPLE, "repo_a"), "repo_a", str(tmp_path))
        assert read_meta(ref.path)["absence"]["absence_is_evidence"] is True

    def test_a_v1_0_artifact_migrates_to_an_honest_unknown(self):
        """Not to an empty report — that would claim the scan was complete
        and found nothing, which is the implied absence C5 removes."""
        from adduce.db.artifact_migrations import migrate

        out = migrate({"wire_version": "1.0.0", "repo_id": "old"})
        assert out["absence"]["absence_is_evidence"] is False
        assert out["absence"]["incomplete_because"]
