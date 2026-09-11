"""A declared-but-unfetched submodule is reported, never passed over.

This is the worst silent gap the scanner can have. An unfetched submodule is
an empty directory: the walk finds nothing, emits nothing, and the graph comes
out smaller with no counter and no warning to say why. And the code that goes
missing is exactly the shared library most likely to be called from other
repositories — the edges this tool exists to find.
"""

from evigraph.services.scan import scan, unfetched_submodules


def _gitmodules(root, *entries):
    root.joinpath(".gitmodules").write_text("\n".join(
        f'[submodule "{name}"]\n\tpath = {path}\n\turl = https://x/{name}.git'
        for name, path in entries))


class TestDetection:
    def test_no_gitmodules_means_nothing_to_report(self, tmp_path):
        assert unfetched_submodules(str(tmp_path)) == []

    def test_empty_directory_is_unfetched(self, tmp_path):
        _gitmodules(tmp_path, ("shared", "libs/shared"))
        (tmp_path / "libs" / "shared").mkdir(parents=True)
        assert unfetched_submodules(str(tmp_path)) == ["libs/shared"]

    def test_missing_directory_is_unfetched(self, tmp_path):
        """`git clone` without --recurse-submodules leaves the path absent
        entirely on some versions, and empty on others. Both are unfetched."""
        _gitmodules(tmp_path, ("shared", "libs/shared"))
        assert unfetched_submodules(str(tmp_path)) == ["libs/shared"]

    def test_populated_submodule_is_not_reported(self, tmp_path):
        _gitmodules(tmp_path, ("shared", "libs/shared"))
        target = tmp_path / "libs" / "shared"
        target.mkdir(parents=True)
        (target / "main.py").write_text("x = 1\n")
        assert unfetched_submodules(str(tmp_path)) == []

    def test_reports_only_the_unfetched_ones(self, tmp_path):
        _gitmodules(tmp_path, ("a", "vendor/a"), ("b", "vendor/b"))
        (tmp_path / "vendor" / "a").mkdir(parents=True)
        fetched = tmp_path / "vendor" / "b"
        fetched.mkdir(parents=True)
        (fetched / "f.py").write_text("y = 2\n")
        assert unfetched_submodules(str(tmp_path)) == ["vendor/a"]

    def test_malformed_gitmodules_does_not_raise(self, tmp_path):
        """A parser that raises on a file it does not recognise takes the
        whole ingest down with it."""
        (tmp_path / ".gitmodules").write_text("not ini at all\n\x00\x01")
        assert unfetched_submodules(str(tmp_path)) == []


class TestReportedByScan:
    def test_scan_surfaces_the_gap(self, tmp_path):
        _gitmodules(tmp_path, ("shared", "libs/shared"))
        (tmp_path / "libs" / "shared").mkdir(parents=True)
        (tmp_path / "app.py").write_text("import os\n")
        assert scan(str(tmp_path), "r").unfetched_submodules == ["libs/shared"]

    def test_clean_repo_reports_nothing(self, tmp_path):
        (tmp_path / "app.py").write_text("import os\n")
        assert scan(str(tmp_path), "r").unfetched_submodules == []
