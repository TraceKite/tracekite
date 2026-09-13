"""`tracekite ingest`: target classification, bundle creation, HTTP calls.

The decline cases matter most here: a directory that is not a repository,
a repository with nothing committed, and a name the server would reject
must fail on the CLI side with guidance, not as a server 400 after an
upload.
"""

import subprocess
from types import SimpleNamespace

import pytest

from tracekite import ingest_client
from tracekite.ingest_client import (
    DirectoryPlan, IngestError, cmd_ingest, create_bundle, plan_directory,
)


def _make_repo(path, branch="main", commit=True):
    subprocess.run(["git", "init", "-b", branch, str(path)],
                   check=True, capture_output=True)
    if not commit:
        return
    (path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-m", "init"],
                   check=True, capture_output=True)


class TestPlanDirectory:
    def test_plain_directory_is_declined(self, tmp_path):
        with pytest.raises(IngestError, match="not a git repository"):
            plan_directory(str(tmp_path), None, None)

    def test_a_repository_without_commits_is_declined(self, tmp_path):
        repo = tmp_path / "proj"
        _make_repo(repo, commit=False)
        with pytest.raises(IngestError, match="no commits yet"):
            plan_directory(str(repo), None, None)

    def test_clean_repo_plans_head_and_current_branch(self, tmp_path):
        repo = tmp_path / "proj"
        _make_repo(repo, branch="trunk")
        plan = plan_directory(str(repo), None, None)
        assert plan == DirectoryPlan(path=str(repo), name="proj",
                                     refs=("HEAD", "trunk"),
                                     server_branch=None)

    def test_explicit_branch_reaches_the_server_clone(self, tmp_path):
        repo = tmp_path / "proj"
        _make_repo(repo)
        plan = plan_directory(str(repo), None, "release")
        assert plan.refs == ("HEAD", "release")
        assert plan.server_branch == "release"

    def test_detached_head_bundles_head_only(self, tmp_path):
        repo = tmp_path / "proj"
        _make_repo(repo)
        sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             check=True, capture_output=True, text=True
                             ).stdout.strip()
        subprocess.run(["git", "-C", str(repo), "checkout", sha],
                       check=True, capture_output=True)
        assert plan_directory(str(repo), None, None).refs == ("HEAD",)

    def test_a_name_the_server_would_reject_fails_early(self, tmp_path):
        repo = tmp_path / "My Proj"
        _make_repo(repo)
        with pytest.raises(IngestError, match="--name"):
            plan_directory(str(repo), None, None)
        plan = plan_directory(str(repo), "my-proj", None)
        assert plan.name == "my-proj"

    def test_uncommitted_changes_are_announced(self, tmp_path, capsys):
        repo = tmp_path / "proj"
        _make_repo(repo)
        (repo / "dirty.py").write_text("x = 1\n")
        plan_directory(str(repo), None, None)
        assert "uncommitted changes" in capsys.readouterr().err


class TestCreateBundle:
    def test_bundle_is_a_real_bundle_with_the_planned_refs(self, tmp_path):
        repo = tmp_path / "proj"
        _make_repo(repo)
        plan = plan_directory(str(repo), None, None)
        bundle = tmp_path / "out.bundle"
        size = create_bundle(plan, str(bundle))

        assert size > 0
        assert open(bundle, "rb").read(16).startswith(b"# v")
        refs = subprocess.run(
            ["git", "ls-remote", str(bundle)],
            check=True, capture_output=True, text=True).stdout
        assert "refs/heads/main" in refs and "HEAD" in refs


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TestIngestUrl:
    def test_a_url_posts_the_ingest_contract(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(ingest_client.httpx, "post",
                            lambda url, **kw: sent.update(url=url, **kw)
                            or FakeResponse(202, {"job_id": "j", "repo_id": "o_r"}))
        args = SimpleNamespace(target="https://github.com/o/r",
                               server="http://s", branch=None, token="t")
        job = ingest_client._ingest_url(args)
        assert sent["url"] == "http://s/api/repos/ingest"
        assert sent["json"] == {"github_url": "https://github.com/o/r",
                                "branch": None, "github_token": "t"}
        assert job["job_id"] == "j"

    def test_neither_url_nor_directory_is_a_clean_error(self):
        args = SimpleNamespace(target="not a url at all", server="http://s",
                               branch=None, token=None)
        with pytest.raises(IngestError, match="not a directory either"):
            ingest_client._ingest_url(args)

    def test_a_server_rejection_surfaces_its_detail(self, monkeypatch):
        monkeypatch.setattr(ingest_client.httpx, "post",
                            lambda *a, **kw: FakeResponse(
                                400, {"detail": "Git host 'x' is not allowlisted"}))
        args = SimpleNamespace(target="https://x.com/o/r", server="http://s",
                               branch=None, token=None)
        with pytest.raises(IngestError, match="not allowlisted"):
            ingest_client._ingest_url(args)


class TestWaitForJob:
    def _polls(self, monkeypatch, statuses):
        calls = iter(statuses)
        monkeypatch.setattr(ingest_client.httpx, "get",
                            lambda *a, **kw: FakeResponse(
                                200, next(calls)))
        monkeypatch.setattr(ingest_client.time, "sleep", lambda _s: None)

    def test_completed_returns_zero(self, monkeypatch):
        self._polls(monkeypatch, [
            {"status": "queued", "progress": 0, "message": "queued"},
            {"status": "running", "progress": 40, "message": "Parsing"},
            {"status": "completed", "progress": 100, "message": "done"},
        ])
        assert ingest_client._wait_for_job("http://s", "j") == 0

    def test_failed_returns_one_with_the_error(self, monkeypatch, capsys):
        self._polls(monkeypatch, [
            {"status": "failed", "progress": 0, "message": "m",
             "error": "git clone failed"},
        ])
        assert ingest_client._wait_for_job("http://s", "j") == 1
        assert "git clone failed" in capsys.readouterr().err


class TestCmdIngest:
    def test_directory_target_uploads_a_bundle(self, tmp_path, monkeypatch):
        repo = tmp_path / "proj"
        _make_repo(repo)
        sent = {}

        def fake_post(url, **kw):
            filename, handle, mime = kw["files"]["file"]
            sent.update(url=url, data=kw["data"], filename=filename,
                        mime=mime, head=handle.read(16))
            return FakeResponse(202, {"job_id": "j-9", "repo_id": "local_proj"})
        monkeypatch.setattr(ingest_client.httpx, "post", fake_post)

        args = SimpleNamespace(target=str(repo), server="http://s",
                               branch=None, token=None, name=None,
                               no_wait=True)
        assert cmd_ingest(args) == 0
        assert sent["url"] == "http://s/api/repos/ingest-upload"
        assert sent["data"] == {"name": "proj"}
        assert sent["filename"] == "proj.bundle"
        assert sent["head"].startswith(b"# v")
