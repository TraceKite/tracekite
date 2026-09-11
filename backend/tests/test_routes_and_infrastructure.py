"""Route and middleware tests: bearer auth, queue-backed repos, graph routes."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tracekite.config import settings
from tracekite.main import app
from tracekite.models.api_models import (
    GraphLink, GraphNode, GraphResponse, GraphStats, NodeDetail, RepoSummary,
)

client = TestClient(app, raise_server_exceptions=False)


def _summary(repo_id="r1"):
    return RepoSummary(id=repo_id, name="foo/bar", owner="foo", repo="bar",
                       github_url="https://github.com/foo/bar", branch="main",
                       ingestion_status="completed",
                       lifecycle_state="ingested", head_commit_sha="abc")


class TestAuth:
    @pytest.fixture(autouse=True)
    def _auth_on(self):
        """Auth is disabled in the shipped compose stack, so these tests must
        assert against the enabled path explicitly.

        Both halves are pinned. `auth_enabled` alone left
        `allow_anonymous_reads` coming from whatever `.env` the developer
        happens to have, and the compose example sets it true — which turned
        a 401 into a read that reached the database and 500'd. CI has no
        `.env`, so the suite passed there and failed locally.
        """
        with patch.object(settings, "auth_enabled", True), \
                patch.object(settings, "allow_anonymous_reads", False):
            yield

    def test_api_requires_token(self):
        response = client.get("/api/repos")
        assert response.status_code == 401

    def test_wrong_token_rejected(self):
        response = client.get(
            "/api/repos", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401

    def test_missing_server_token_disables_api(self, auth_headers):
        with patch.object(settings, "api_token", ""):
            response = client.get("/api/repos", headers=auth_headers)
        assert response.status_code == 503

    def test_health_is_public(self):
        with patch("tracekite.routes.health.check_neo4j_health", return_value=True):
            response = client.get("/health")
        assert response.status_code == 200

    def test_root_is_public(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "version" in response.json()

    def test_valid_token_passes(self, auth_headers):
        with patch("tracekite.routes.repos.list_repos", return_value=[]):
            response = client.get("/api/repos", headers=auth_headers)
        assert response.status_code == 200

    # ALLOW_ANONYMOUS_READS lets the UI browse without a credential. The
    # split it depends on is security-critical: reads open, writes never.
    def test_anonymous_read_allowed_when_enabled(self):
        with patch.object(settings, "allow_anonymous_reads", True), \
             patch("tracekite.routes.repos.list_repos", return_value=[]):
            response = client.get("/api/repos")
        assert response.status_code == 200

    def test_anonymous_write_still_rejected_when_reads_open(self):
        with patch.object(settings, "allow_anonymous_reads", True):
            ingest = client.post("/api/repos/ingest",
                                 json={"github_url": "https://github.com/a/b"})
            delete = client.delete("/api/repos/some-repo")
            rebuild = client.post("/api/v2/links/rebuild")
        assert ingest.status_code == 401
        assert delete.status_code == 401
        assert rebuild.status_code == 401

    def test_anonymous_write_rejected_even_with_no_server_token(self):
        # No token configured must not become "no auth needed" for writes.
        with patch.object(settings, "allow_anonymous_reads", True), \
             patch.object(settings, "api_token", ""):
            response = client.delete("/api/repos/some-repo")
        assert response.status_code == 503

    def test_reads_still_require_token_when_disabled(self):
        with patch.object(settings, "allow_anonymous_reads", False):
            response = client.get("/api/repos")
        assert response.status_code == 401

    def test_health_reports_anonymous_read_mode(self):
        with patch.object(settings, "allow_anonymous_reads", True), \
             patch("tracekite.routes.health.check_neo4j_health", return_value=True):
            body = client.get("/health").json()
        assert body["anonymous_reads"] is True
        assert body["auth_required_for_writes"] is True

    def test_auth_disabled_allows_everything(self):
        # The escape hatch the local stack ships with: no token for any route.
        with patch.object(settings, "auth_enabled", False), \
             patch("tracekite.routes.repos.list_repos", return_value=[]):
            read = client.get("/api/repos")
        assert read.status_code == 200
        with patch.object(settings, "auth_enabled", False):
            delete = client.delete("/api/repos/some-repo")
        assert delete.status_code != 401

    def test_health_reports_auth_disabled(self):
        with patch.object(settings, "auth_enabled", False), \
             patch("tracekite.routes.health.check_neo4j_health", return_value=True):
            body = client.get("/health").json()
        assert body["auth_required_for_writes"] is False
        assert body["anonymous_reads"] is True

    def test_rate_limiter_blocks_after_burst(self):
        from tracekite.middleware.auth import _limiter
        results = [_limiter.allow("burst-test-key") for _ in range(40)]
        assert False in results


class TestHealthRoute:
    def test_health_ok(self):
        # The posture is asserted, so it is also pinned: /health reports live
        # settings, and a local `.env` would otherwise decide the expectation.
        with patch("tracekite.routes.health.check_neo4j_health", return_value=True), \
                patch.object(settings, "auth_enabled", True), \
                patch.object(settings, "allow_anonymous_reads", False):
            body = client.get("/health").json()
        assert body == {"status": "ok", "neo4j": "ok",
                        "anonymous_reads": False,
                        "auth_required_for_writes": True}

    def test_health_degraded(self):
        with patch("tracekite.routes.health.check_neo4j_health", return_value=False):
            body = client.get("/health").json()
        assert body["status"] == "degraded"


class TestReposRoutes:
    def test_ingest_queues_job(self, auth_headers):
        with patch("tracekite.routes.repos.job_queue") as queue:
            queue.submit.return_value = "job-123"
            response = client.post(
                "/api/repos/ingest",
                json={"github_url": "https://github.com/foo/bar"},
                headers=auth_headers,
            )
        assert response.status_code == 202
        body = response.json()
        assert body["job_id"] == "job-123"
        assert body["status"] == "queued"
        args, kwargs = queue.submit.call_args
        assert args[0] == "ingest"
        assert kwargs["payload"]["github_url"].startswith(
            "https://github.com/foo/bar")

    def test_ingest_refresh_flag_uses_refresh_lane(self, auth_headers):
        with patch("tracekite.routes.repos.job_queue") as queue:
            queue.submit.return_value = "job-124"
            client.post(
                "/api/repos/ingest",
                json={"github_url": "https://github.com/foo/bar",
                      "refresh": True},
                headers=auth_headers,
            )
        assert queue.submit.call_args[0][0] == "refresh"

    def test_ingest_rejects_bad_url(self, auth_headers):
        response = client.post("/api/repos/ingest",
                               json={"github_url": "not-a-url"},
                               headers=auth_headers)
        assert response.status_code == 400

    def test_ingest_rejects_non_allowlisted_host(self, auth_headers):
        response = client.post(
            "/api/repos/ingest",
            json={"github_url": "https://evilhost.com/foo/bar"},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_list_repositories(self, auth_headers):
        with patch("tracekite.routes.repos.list_repos",
                   return_value=[_summary()]):
            body = client.get("/api/repos", headers=auth_headers).json()
        assert len(body["repos"]) == 1
        assert body["repos"][0]["lifecycle_state"] == "ingested"

    def test_get_repository_found(self, auth_headers):
        with patch("tracekite.routes.repos.get_repo", return_value=_summary()):
            response = client.get("/api/repos/r1", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["head_commit_sha"] == "abc"

    def test_get_repository_missing(self, auth_headers):
        with patch("tracekite.routes.repos.get_repo", return_value=None):
            response = client.get("/api/repos/nope", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_queues_job(self, auth_headers):
        with patch("tracekite.routes.repos.get_repo", return_value=_summary()), \
             patch("tracekite.routes.repos.job_queue") as queue:
            queue.submit.return_value = "job-del"
            response = client.delete("/api/repos/r1", headers=auth_headers)
        assert response.status_code == 202
        assert response.json()["job_id"] == "job-del"
        assert queue.submit.call_args[0][0] == "repo_delete"

    def test_refresh_queues_job(self, auth_headers):
        with patch("tracekite.routes.repos.get_repo", return_value=_summary()), \
             patch("tracekite.routes.repos.job_queue") as queue:
            queue.submit.return_value = "job-ref"
            response = client.post("/api/repos/r1/refresh",
                                   headers=auth_headers)
        assert response.status_code == 202
        payload = queue.submit.call_args[1]["payload"]
        assert payload["github_url"] == "https://github.com/foo/bar"


class TestJobsRoute:
    def test_job_status_found(self, auth_headers):
        record = {"job_id": "j1", "repo_id": "r1", "status": "running",
                  "progress": 50, "message": "Parsing", "error": None,
                  "created_at": None, "updated_at": None}
        session = MagicMock()
        session.run.return_value.single.return_value = record
        ctx = MagicMock()
        ctx.__enter__.return_value = session
        with patch("tracekite.routes.jobs.get_session", return_value=ctx):
            body = client.get("/api/jobs/j1", headers=auth_headers).json()
        assert body["status"] == "running"
        assert body["progress"] == 50

    def test_job_status_missing(self, auth_headers):
        session = MagicMock()
        session.run.return_value.single.return_value = None
        ctx = MagicMock()
        ctx.__enter__.return_value = session
        with patch("tracekite.routes.jobs.get_session", return_value=ctx):
            response = client.get("/api/jobs/nope", headers=auth_headers)
        assert response.status_code == 404


class TestGraphRoutes:
    def test_get_graph(self, auth_headers):
        fake = GraphResponse(
            repo=_summary(),
            stats=GraphStats(total_nodes=1, total_edges=1),
            nodes=[GraphNode(id="n1", type="File", label="a.py", name="a.py")],
            links=[GraphLink(source="r1", target="n1", type="CONTAINS",
                             label="contains", confidence=1.0)],
        )
        with patch("tracekite.routes.graph.get_graph", return_value=fake):
            body = client.get("/api/repos/r1/graph",
                              headers=auth_headers).json()
        assert body["links"][0]["confidence"] == 1.0
        assert body["links"][0]["type"] == "CONTAINS"

    def test_search(self, auth_headers):
        with patch("tracekite.routes.graph.search_nodes", return_value=[]):
            response = client.get("/api/repos/r1/search?q=foo",
                                  headers=auth_headers)
        assert response.status_code == 200

    def test_node_detail_missing(self, auth_headers):
        with patch("tracekite.routes.graph.get_node_details", return_value=None):
            response = client.get("/api/repos/r1/nodes/x",
                                  headers=auth_headers)
        assert response.status_code == 404

    def test_node_detail_found(self, auth_headers):
        detail = NodeDetail(
            node=GraphNode(id="n1", type="Method", label="m", name="m"),
            incoming=[], outgoing=[], neighbors=[],
        )
        with patch("tracekite.routes.graph.get_node_details", return_value=detail):
            response = client.get("/api/repos/r1/nodes/n1",
                                  headers=auth_headers)
        assert response.status_code == 200


class TestModels:
    def test_graph_link_confidence_is_float(self):
        link = GraphLink(source="a", target="b", type="CALLS", label="calls")
        assert isinstance(link.confidence, float)
        assert link.confidence == 1.0

    def test_repo_summary_new_fields_optional(self):
        summary = _summary()
        assert summary.parse_coverage is None
        assert summary.lifecycle_state == "ingested"
