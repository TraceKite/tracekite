"""Upload ingest: the name rule, bundle validation, the route, and the
refresh decline for repositories that have no remote to re-clone."""

import io
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from tracekite import engine_config
from tracekite.main import app
from tracekite.routes import repos as repos_route
from tracekite.services import ingest_upload
from tracekite.services.repo_service import (
    CloneError, clone_bundle, get_head_commit_sha,
)
from tracekite.utils.hashing import upload_repo_id

from .conftest import AUTH_HEADERS

client = TestClient(app, raise_server_exceptions=False)

BUNDLE_HEAD = b"# v2 git bundle\n"


class TestUploadRepoId:
    def test_namespaces_under_local(self):
        assert upload_repo_id("my-proj_1.2") == "local_my-proj_1.2"

    @pytest.mark.parametrize("name", [
        "", "MyProj", "has space", "..", "../etc", "a/b", "-lead", "a" * 100,
    ])
    def test_rejects_names_that_would_lie_or_escape(self, name):
        # The name becomes a filename and a graph id; rewriting it silently
        # would make the CLI and the server disagree about what was ingested.
        with pytest.raises(ValueError, match="invalid repository name"):
            upload_repo_id(name)


class TestStoreBundle:
    def _upload(self, data: bytes) -> UploadFile:
        return UploadFile(file=io.BytesIO(data), filename="x.bundle")

    def test_rejects_non_bundle_and_leaves_nothing(self, tmp_path,
                                                   monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path))
        with pytest.raises(ValueError, match="not a git bundle"):
            ingest_upload.store_bundle(self._upload(b"garbage"), "ok")
        assert list(tmp_path.iterdir()) == []

    def test_streams_to_disk_under_a_unique_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path))
        payload = BUNDLE_HEAD + b"0" * 100
        repo_id, path = ingest_upload.store_bundle(self._upload(payload),
                                                   "demo")
        assert repo_id == "local_demo"
        assert open(path, "rb").read() == payload
        _, second = ingest_upload.store_bundle(self._upload(payload), "demo")
        assert second != path          # concurrent same-name uploads differ

    def test_bad_name_is_rejected_before_any_write(self, tmp_path,
                                                   monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path))
        with pytest.raises(ValueError, match="invalid repository name"):
            ingest_upload.store_bundle(self._upload(BUNDLE_HEAD), "Bad Name")
        assert list(tmp_path.iterdir()) == []

    def test_oversize_bundle_is_rejected_and_leaves_no_file(self, tmp_path,
                                                             monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path))
        monkeypatch.setattr(ingest_upload, "MAX_BUNDLE_BYTES", 200)
        payload = BUNDLE_HEAD + b"0" * 300
        with pytest.raises(ValueError, match="exceeds the"):
            ingest_upload.store_bundle(self._upload(payload), "demo")
        assert list(tmp_path.iterdir()) == []


class TestUploadRoute:
    def test_anonymous_upload_is_rejected(self):
        # The local .env disables auth entirely; pin the behaviour under the
        # secured configuration, where a write must never pass anonymously.
        with patch.object(repos_route.settings, "auth_enabled", True):
            response = client.post(
                "/api/repos/ingest-upload", data={"name": "demo"},
                files={"file": ("demo.bundle", BUNDLE_HEAD)})
        assert response.status_code == 401

    def test_bad_name_is_a_400(self):
        response = client.post(
            "/api/repos/ingest-upload", data={"name": "Bad Name"},
            files={"file": ("demo.bundle", BUNDLE_HEAD)},
            headers=AUTH_HEADERS)
        assert response.status_code == 400
        assert "invalid repository name" in response.json()["detail"]

    def test_non_bundle_is_a_400(self):
        with patch.object(repos_route, "get_repo", return_value=None):
            response = client.post(
                "/api/repos/ingest-upload", data={"name": "demo"},
                files={"file": ("demo.bundle", b"plain text")},
                headers=AUTH_HEADERS)
        assert response.status_code == 400
        assert "not a git bundle" in response.json()["detail"]

    def test_happy_path_queues_an_upload_job(self, tmp_path):
        engine_config.configure(workspace_dir=str(tmp_path / "repos"))
        submitted = {}
        try:
            def fake_submit(job_type, repo_id, payload=None, job_id=None):
                submitted.update(type=job_type, repo=repo_id, payload=payload)
                return "job-1"
            with patch.object(repos_route, "get_repo", return_value=None), \
                    patch.object(repos_route.job_queue, "submit", fake_submit):
                response = client.post(
                    "/api/repos/ingest-upload", data={"name": "demo"},
                    files={"file": ("demo.bundle", BUNDLE_HEAD + b"0" * 50)},
                    headers=AUTH_HEADERS)
        finally:
            engine_config.reset()
        assert response.status_code == 202
        body = response.json()
        assert body["repo_id"] == "local_demo"
        assert body["job_id"] == "job-1"
        assert submitted["type"] == "ingest_upload"
        assert submitted["payload"]["name"] == "demo"
        bundle_path = submitted["payload"]["bundle_path"]
        assert open(bundle_path, "rb").read().startswith(BUNDLE_HEAD)


class TestRefreshDecline:
    def test_a_local_upload_has_no_remote_to_refresh_from(self):
        repo = SimpleNamespace(github_url="", branch="main")
        with patch.object(repos_route, "get_repo", return_value=repo):
            response = client.post("/api/repos/local_demo/refresh",
                                   headers=AUTH_HEADERS)
        assert response.status_code == 400
        assert "tracekite ingest ." in response.json()["detail"]

    def test_a_hosted_repo_still_refreshes(self):
        repo = SimpleNamespace(github_url="https://github.com/o/r",
                               branch="main")
        with patch.object(repos_route, "get_repo", return_value=repo), \
                patch.object(repos_route.job_queue, "submit",
                             return_value="j-1") as submit:
            response = client.post("/api/repos/o_r/refresh",
                                   headers=AUTH_HEADERS)
        assert response.status_code == 202
        assert submit.call_args[1]["payload"]["github_url"] == \
            "https://github.com/o/r"

    def test_upload_declines_when_hosted_repo_exists(self):
        repo = SimpleNamespace(
            github_url="https://github.com/local/demo", branch="main")
        with patch.object(repos_route, "get_repo", return_value=repo):
            response = client.post(
                "/api/repos/ingest-upload", data={"name": "demo"},
                files={"file": ("demo.bundle", BUNDLE_HEAD + b"0" * 50)},
                headers=AUTH_HEADERS)
        assert response.status_code == 400
        assert "already in use" in response.json()["detail"]


def _make_repo(path, branch="main"):
    subprocess.run(["git", "init", "-b", branch, str(path)],
                   check=True, capture_output=True)
    (path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-m", "init"],
                   check=True, capture_output=True)


class TestCloneBundle:
    def test_clones_the_uploaded_content(self, tmp_path):
        engine_config.configure(workspace_dir=str(tmp_path / "ws"))
        try:
            src = tmp_path / "src"
            _make_repo(src)
            bundle = tmp_path / "demo.bundle"
            subprocess.run(
                ["git", "-C", str(src), "bundle", "create", str(bundle),
                 "HEAD", "main"], check=True, capture_output=True)

            dest = clone_bundle(str(bundle), "local_demo")

            assert open(f"{dest}/app.py").read() == "print('hi')\n"
            assert get_head_commit_sha(dest) == get_head_commit_sha(str(src))
        finally:
            engine_config.reset()

    def test_a_bad_bundle_keeps_the_previous_tree(self, tmp_path):
        engine_config.configure(workspace_dir=str(tmp_path / "ws"))
        try:
            existing = tmp_path / "ws" / "local_demo"
            existing.mkdir(parents=True)
            (existing / "marker").write_text("previous")

            with pytest.raises(CloneError):
                clone_bundle(str(tmp_path / "missing.bundle"), "local_demo")

            assert (existing / "marker").read_text() == "previous"
        finally:
            engine_config.reset()

    def test_detached_head_stamps_sha_not_main(self, tmp_path):
        from tracekite.services.repo_service import get_default_branch
        engine_config.configure(workspace_dir=str(tmp_path / "ws"))
        try:
            src = tmp_path / "src"
            _make_repo(src, branch="release-2.1")
            sha = subprocess.run(
                ["git", "-C", str(src), "rev-parse", "HEAD"],
                check=True, capture_output=True, text=True).stdout.strip()
            subprocess.run(
                ["git", "-C", str(src), "checkout", sha],
                check=True, capture_output=True)
            branch = get_default_branch(str(src))
            assert branch != "main"
            assert branch == sha[:7]
        finally:
            engine_config.reset()


class TestNoDedup:
    """ingest_upload carries different content each time; coalescing would
    silently drop the new bundle and the CLI would report success for
    content the server never opened."""

    def test_ingest_upload_does_not_coalesce(self):
        from tracekite.services import job_queue as jq_module
        q = jq_module.JobQueue(ingest_workers=1)
        with patch.object(jq_module, "create_or_update_job"):
            j1 = q.submit("ingest_upload", "local_demo",
                          payload={"bundle_path": "/tmp/a.bundle"})
            j2 = q.submit("ingest_upload", "local_demo",
                          payload={"bundle_path": "/tmp/b.bundle"})
        assert j1 != j2
        q.stop()

    def test_ingest_still_coalesces(self):
        from tracekite.services import job_queue as jq_module
        q = jq_module.JobQueue(ingest_workers=1)
        with patch.object(jq_module, "create_or_update_job"):
            j1 = q.submit("ingest", "o_r", payload={"github_url": "..."})
            j2 = q.submit("ingest", "o_r", payload={"github_url": "..."})
        assert j1 == j2
        q.stop()


class TestSweepUploadDir:
    def test_sweeps_orphaned_bundles(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path))
        (tmp_path / "local_a-abc.bundle").write_bytes(b"x")
        (tmp_path / "local_b-def.bundle").write_bytes(b"y")
        (tmp_path / "not-a-bundle.txt").write_text("keep me")
        count = ingest_upload.sweep_upload_dir()
        assert count == 2
        assert list(tmp_path.iterdir()) == [tmp_path / "not-a-bundle.txt"]

    def test_empty_when_no_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ingest_upload, "get_upload_dir",
                            lambda: str(tmp_path / "missing"))
        assert ingest_upload.sweep_upload_dir() == 0


class TestIngestionSource:
    def _repo(self):
        from tracekite.services.ingestion_service import ClonedRepo
        return ClonedRepo(
            owner="local", name="demo", url="", branch="main",
            head_sha="deadbeef", path="/repo", source="upload")

    def test_missing_repo_node_fails_clean(self):
        from tracekite.services import ingestion_service
        sink = SimpleNamespace(nodes=[])
        with patch.object(ingestion_service, "scan_repository"), \
             patch.object(ingestion_service, "_job"), \
             patch.object(ingestion_service, "_lifecycle"), \
             patch.object(ingestion_service, "build_graph", return_value=sink), \
             patch.object(ingestion_service, "_mark_failed") as mark_failed:
            ingestion_service._scan_and_write("job-1", "local_demo",
                                               self._repo(), refresh=False)
        error = mark_failed.call_args.args[2]
        assert isinstance(error, RuntimeError)
        assert "produced no Repo node" in str(error)
        assert mark_failed.call_args.args[3] is False

    def test_stamps_explicit_source_on_repo_node(self):
        from tracekite.services import ingestion_service
        repo_node = SimpleNamespace(id="local_demo", extra_props={})
        sink = SimpleNamespace(nodes=[repo_node], edges=[], parse_context={},
                               coverage={}, claims={})
        with patch.object(ingestion_service, "scan_repository"), \
             patch.object(ingestion_service, "_job"), \
             patch.object(ingestion_service, "_lifecycle"), \
             patch.object(ingestion_service, "build_graph", return_value=sink), \
             patch.object(ingestion_service, "build_call_graph"), \
             patch.object(ingestion_service.graph_writer, "write_nodes_batch",
                          return_value=1), \
             patch.object(ingestion_service.graph_writer, "write_edges_batch",
                          return_value={}), \
             patch.object(ingestion_service.graph_writer, "update_repo_stats"), \
             patch.object(ingestion_service.graph_writer, "set_repo_lifecycle"), \
             patch.object(ingestion_service, "_stamp_coverage"), \
             patch.object(ingestion_service, "_set_ingestion_status"):
            ingestion_service._scan_and_write("job-1", "local_demo",
                                               self._repo(), refresh=False)
        assert repo_node.extra_props["source"] == "upload"
