"""A failed refresh leaves the working tree exactly as it was.

`clone_repository` used to delete the destination and then clone into it,
which makes refresh DESTRUCTIVE on any repository the clone cannot reach: a
private remote whose token expired loses its working tree, cannot get it
back, and the repo goes `failed_clean` while the graph still holds its
claims. It happened twice on this project's own estate — the second time
after the hazard was already written down — which is the argument for a
test rather than a note.

The ingest pipeline already follows this rule at the graph level: it clears
a repo's nodes only after a successful scan. This is the same rule one
layer down.
"""

import os

import pytest

from adduce.services import repo_service
from adduce.services.repo_service import CloneError, clone_repository


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(repo_service, "get_repo_workspace_path",
                        lambda repo_id: os.path.join(str(tmp_path), repo_id))
    monkeypatch.setattr(repo_service, "ensure_workspace", lambda: None)
    # `allowed_hosts_list` is a method on a pydantic model, so it is patched
    # on the class rather than the instance.
    monkeypatch.setattr(type(repo_service.settings), "allowed_hosts_list",
                        lambda self: ["github.com"])
    return tmp_path


def existing_clone(workspace, repo_id="acme_web"):
    tree = workspace / repo_id
    (tree / ".git").mkdir(parents=True)
    (tree / ".git" / "config").write_text("[core]\n")
    (tree / "main.py").write_text("print('the tree that must survive')\n")
    return tree


class TestFailedCloneKeepsTheTree:
    def test_an_unreachable_remote_does_not_delete_the_working_tree(
            self, workspace, monkeypatch):
        tree = existing_clone(workspace)

        def failing_run(*args, **kwargs):
            class Result:
                returncode = 128
                stderr = "fatal: could not read Username: terminal prompts disabled"
                stdout = ""
            return Result()

        monkeypatch.setattr(repo_service.subprocess, "run", failing_run)
        with pytest.raises(CloneError):
            clone_repository("https://github.com/acme/web", "acme_web")

        assert tree.exists(), "the working tree was deleted by a failed clone"
        assert (tree / "main.py").read_text().endswith("survive')\n")

    def test_a_timeout_does_not_delete_the_working_tree(
            self, workspace, monkeypatch):
        import subprocess as sp
        tree = existing_clone(workspace)

        def timing_out(*args, **kwargs):
            raise sp.TimeoutExpired(cmd="git", timeout=1)

        monkeypatch.setattr(repo_service.subprocess, "run", timing_out)
        with pytest.raises(CloneError):
            clone_repository("https://github.com/acme/web", "acme_web")
        assert (tree / "main.py").exists()

    def test_a_disallowed_host_never_touches_the_tree(self, workspace):
        tree = existing_clone(workspace)
        with pytest.raises(CloneError):
            clone_repository("https://evil.example/acme/web", "acme_web")
        assert (tree / "main.py").exists()


class TestSuccessfulCloneReplacesIt:
    def test_the_new_tree_wins_and_no_staging_is_left_behind(
            self, workspace, monkeypatch):
        existing_clone(workspace)

        def fake_clone(cmd, **kwargs):
            dest = cmd[-1]                      # clones into staging
            os.makedirs(os.path.join(dest, ".git"))
            with open(os.path.join(dest, ".git", "config"), "w") as handle:
                handle.write("[core]\n")
            with open(os.path.join(dest, "main.py"), "w") as handle:
                handle.write("print('fresh')\n")

            class Result:
                returncode = 0
                stderr = ""
                stdout = ""
            return Result()

        monkeypatch.setattr(repo_service.subprocess, "run", fake_clone)
        path = clone_repository("https://github.com/acme/web", "acme_web")

        assert open(os.path.join(path, "main.py")).read() == "print('fresh')\n"
        siblings = sorted(p.name for p in workspace.iterdir())
        assert siblings == ["acme_web"], (
            f"staging or backup left behind: {siblings}")

    def test_it_clones_into_staging_not_over_the_live_tree(
            self, workspace, monkeypatch):
        """The property that makes the failure cases above possible: the
        live tree is still there while the clone runs."""
        tree = existing_clone(workspace)
        seen = {}

        def observe(cmd, **kwargs):
            seen["target"] = cmd[-1]
            seen["tree_alive"] = (tree / "main.py").exists()
            raise repo_service.subprocess.TimeoutExpired(cmd="git", timeout=1)

        monkeypatch.setattr(repo_service.subprocess, "run", observe)
        with pytest.raises(CloneError):
            clone_repository("https://github.com/acme/web", "acme_web")
        assert seen["target"].endswith(".incoming")
        assert seen["tree_alive"] is True


class TestNoDebrisIsLeftBehind:
    """A leaked staging tree is not just clutter: `git clone` refuses a
    non-empty target, so debris from one failure can break the next attempt."""

    def _run(self, workspace, monkeypatch, failure):
        existing_clone(workspace)
        monkeypatch.setattr(repo_service.subprocess, "run", failure)
        with pytest.raises(CloneError):
            clone_repository("https://github.com/acme/web", "acme_web")
        return sorted(p.name for p in workspace.iterdir())

    def test_a_nonzero_exit_leaves_no_staging(self, workspace, monkeypatch):
        def failing(cmd, **kwargs):
            os.makedirs(os.path.join(cmd[-1], ".git"), exist_ok=True)

            class Result:
                returncode = 128
                stderr = "fatal: authentication failed"
                stdout = ""
            return Result()

        assert self._run(workspace, monkeypatch, failing) == ["acme_web"]

    def test_a_timeout_leaves_no_staging(self, workspace, monkeypatch):
        """The path a sibling `except` clause would have missed: converting
        TimeoutExpired into CloneError propagates the new exception."""
        def timing_out(cmd, **kwargs):
            os.makedirs(os.path.join(cmd[-1], ".git"), exist_ok=True)
            raise repo_service.subprocess.TimeoutExpired(cmd="git", timeout=1)

        assert self._run(workspace, monkeypatch, timing_out) == ["acme_web"]

    def test_a_credential_leak_is_rejected_and_cleaned(self, workspace,
                                                       monkeypatch):
        def leaky(cmd, **kwargs):
            git = os.path.join(cmd[-1], ".git")
            os.makedirs(git, exist_ok=True)
            with open(os.path.join(git, "config"), "w") as handle:
                handle.write("[remote]\n  url = https://x:tok@github.com/a/b\n")

            class Result:
                returncode = 0
                stderr = ""
                stdout = ""
            return Result()

        assert self._run(workspace, monkeypatch, leaky) == ["acme_web"]
