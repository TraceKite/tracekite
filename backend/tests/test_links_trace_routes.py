"""Coverage for links/trace routes and auth middleware edge cases (M1/VQ1)."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from evigraph.main import app

client = TestClient(app, raise_server_exceptions=False)


def _session_ctx(session):
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    return ctx


class TestLinksRebuild:
    def test_rebuild_queues_link_full(self, auth_headers):
        with patch("evigraph.routes.links.job_queue") as queue:
            queue.submit.return_value = "job-link-1"
            response = client.post("/api/v2/links/rebuild", headers=auth_headers)
        assert response.status_code == 202
        body = response.json()
        assert body == {"job_id": "job-link-1", "status": "queued"}
        args, _ = queue.submit.call_args
        assert args[0] == "link_full"
        assert args[1] == "__linker__"


class TestLinksStatus:
    def test_status_with_stale_repos(self, auth_headers):
        runs = [{"run_id": "run-1"}, {"run_id": "run-2"}]
        session = MagicMock()
        session.run.return_value = [{"id": "repo-a"}, {"id": "repo-b"}]
        with patch("evigraph.routes.links.list_link_runs", return_value=runs), \
             patch("evigraph.routes.links.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/links/status", headers=auth_headers).json()
        assert body["runs"] == runs
        assert body["latest"] == runs[0]
        assert len(body["warnings"]) == 1
        warning = body["warnings"][0]
        assert warning["kind"] == "links_stale"
        assert warning["repo_ids"] == ["repo-a", "repo-b"]
        assert "2 repo(s)" in warning["detail"]

    def test_status_without_stale_repos(self, auth_headers):
        session = MagicMock()
        session.run.return_value = []
        with patch("evigraph.routes.links.list_link_runs", return_value=[]), \
             patch("evigraph.routes.links.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/links/status", headers=auth_headers).json()
        assert body["runs"] == []
        assert body["latest"] is None
        assert body["warnings"] == []



def _count_result(value):
    """A mocked `RETURN count(r) AS c` row."""
    result = MagicMock()
    result.single.return_value = {"c": value}
    return result

class TestServiceMap:
    def test_service_map_full(self, auth_headers):
        node_rows = [
            {"id": "svc-a", "name": "Service A", "repo_ids": ["r1"],
             "is_gateway": True},
            {"id": "svc-b", "name": "Service B", "repo_ids": None,
             "is_gateway": False},
        ]
        edge_rows = [
            {
                "source": "svc-a", "source_labels": ["Service"],
                "source_name": "Service A", "source_scope": "s",
                "target": "repo-x", "target_labels": ["Repo"],
                "target_name": "Repo X", "target_scope": "rs",
                "type": "BUILT_FROM", "confidence": 0.9,
                "min_confidence": 0.8, "max_confidence": 1.0,
                "via": ["v1"], "weight": 2, "path_prefix": "/x", "source_repo_id": "repo-a",
                "evidence": ["e1", "e2", "e3", "e4"],
            },
            {
                "source": "name-y", "source_labels": ["ServiceName"],
                "source_name": "Name Y", "source_scope": "ns",
                "target": "other-z", "target_labels": ["Other"],
                "target_name": "Other Z", "target_scope": "os",
                "type": "CALLS_SERVICE", "confidence": 0.7,
                "min_confidence": None, "max_confidence": None,
                "via": None, "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                "evidence": None,
            },
        ]
        session = MagicMock()
        node_result = MagicMock()
        node_result.data.return_value = node_rows
        edge_result = MagicMock()
        edge_result.data.return_value = edge_rows
        session.run.side_effect = [node_result, edge_result,
                                   _count_result(len(edge_rows))]
        with patch("evigraph.db.impact_reader.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/service-map?min_confidence=0.5",
                              headers=auth_headers).json()
        # min_confidence passthrough
        edge_call = session.run.call_args_list[1]
        assert edge_call.kwargs["minc"] == 0.5

        nodes = {n["id"]: n for n in body["nodes"]}
        assert nodes["svc-a"]["is_gateway"] is True
        assert nodes["svc-a"]["kind"] == "service"
        assert nodes["svc-a"]["repo_ids"] == ["r1"]
        assert nodes["svc-b"]["repo_ids"] == []
        # edge-side hydration into repo / service_name / node kinds
        assert nodes["repo-x"]["kind"] == "repo"
        assert nodes["repo-x"]["scope"] == "rs"
        assert nodes["name-y"]["kind"] == "service_name"
        assert nodes["name-y"]["dead_end"] is True
        assert nodes["other-z"]["kind"] == "node"
        assert nodes["other-z"]["dead_end"] is False

        edges = body["edges"]
        assert len(edges) == 2
        # evidence truncated to 3
        assert edges[0]["evidence"] == ["e1", "e2", "e3"]
        assert edges[1]["evidence"] == []
        assert edges[1]["via"] == []
        assert body["totals"] == {"services": 2, "edges": 2}
        assert body["truncated"] is False

    def test_service_map_truncated_by_limit(self, auth_headers):
        edge_rows = [
            {
                "source": "svc-a", "source_labels": ["Service"],
                "source_name": "A", "source_scope": None,
                "target": "svc-b", "target_labels": ["Service"],
                "target_name": "B", "target_scope": None,
                "type": "CALLS_SERVICE", "confidence": 0.9,
                "min_confidence": 0.8, "max_confidence": 1.0,
                "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                "evidence": [],
            },
            {
                "source": "svc-b", "source_labels": ["Service"],
                "source_name": "B", "source_scope": None,
                "target": "svc-c", "target_labels": ["Service"],
                "target_name": "C", "target_scope": None,
                "type": "CALLS_SERVICE", "confidence": 0.7,
                "min_confidence": 0.6, "max_confidence": 0.9,
                "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                "evidence": [],
            },
        ]
        session = MagicMock()
        node_result = MagicMock()
        node_result.data.return_value = []
        edge_result = MagicMock()
        # The endpoint LIMITs in Cypher now, so the driver returns one row
        # while the count query still reports the true total of two.
        edge_result.data.return_value = edge_rows[:1]
        session.run.side_effect = [node_result, edge_result,
                                   _count_result(len(edge_rows))]
        with patch("evigraph.db.impact_reader.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/service-map?limit=1",
                              headers=auth_headers).json()
        assert len(body["edges"]) == 1
        assert body["truncated"] is True
        assert body["totals"]["edges"] == 2

    def test_service_map_empty(self, auth_headers):
        session = MagicMock()
        node_result = MagicMock()
        node_result.data.return_value = []
        edge_result = MagicMock()
        edge_result.data.return_value = []
        session.run.side_effect = [node_result, edge_result, _count_result(0)]
        with patch("evigraph.db.impact_reader.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/service-map", headers=auth_headers).json()
        assert body["nodes"] == []
        assert body["edges"] == []
        assert body["totals"] == {"services": 0, "edges": 0}
        assert body["truncated"] is False


def _resolve_rows():
    return [
        {"id": "svc-1", "name": "Alpha"},
        {"id": "svc-2", "name": "Beta"},
    ]


def _fake_trace_session(services, path_rows=None, crossing_rows=None,
                        stale_repos=(), failed_partial=0, on_path_query=None):
    """Session double that answers by query intent rather than exact text.

    The route issues five distinct reads (exact resolve, case-insensitive
    resolve, suggestions, path enumeration, staleness). Matching on intent keeps
    these tests from breaking every time a WHERE clause is reworded.
    """
    def run(query, *args, **kwargs):
        res = MagicMock()
        if "s.id = $q OR s.name = $q" in query:
            q = kwargs.get("q")
            hit = next((s for s in services if q in (s["id"], s["name"])), None)
            res.single.return_value = {"id": hit["id"]} if hit else None
        elif "toLower(s.name) = toLower($q)" in query:
            q = (kwargs.get("q") or "").lower()
            hit = next((s for s in services
                        if (s["name"] or "").lower() == q), None)
            res.single.return_value = {"id": hit["id"]} if hit else None
        elif "RETURN s.name AS name" in query:
            res.data.return_value = [{"name": s["name"]} for s in services][:20]
        elif "lifecycle_state IN" in query:
            res.__iter__ = lambda self: iter(
                [{"id": r} for r in stale_repos])
        elif "failed_partial" in query:
            res.single.return_value = {"c": failed_partial}
        else:
            if on_path_query is not None:
                on_path_query(kwargs)
            res.data.return_value = list(path_rows or [])
            if crossing_rows is not None and "MATCH (a:GraphNode" in query:
                res.data.return_value = list(crossing_rows)
        return res

    session = MagicMock()
    session.run.side_effect = run
    return session


class TestTrace:
    def test_resolve_unknown_returns_404(self, auth_headers):
        # Build many services to exercise the 20-suggestion cap.
        rows = [{"id": f"svc-{i}", "name": f"Svc{i}"} for i in range(30)]
        session = _fake_trace_session(rows)
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            response = client.get(
                "/api/v2/trace?from_service=nope&to_service=Svc0",
                headers=auth_headers)
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["error"] == "service_not_found"
        assert detail["from_resolved"] is None
        assert len(detail["suggestions"]) == 20

    def test_trace_by_exact_id_and_case_insensitive_name(self, auth_headers):
        rows = _resolve_rows()
        path_row = {
            "nodes": [{"id": "svc-1", "name": "Alpha", "labels": ["Service"]},
                      {"id": "svc-2", "name": "Beta", "labels": ["Service"]}],
            "edges": [{"type": "CALLS_SERVICE", "confidence": 0.9,
                       "min_confidence": 0.8, "max_confidence": 1.0,
                       "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                       "evidence": [], "evidence_edge_ids": []}],
            "path_min": 0.8,
        }

        def check(kwargs):
            assert kwargs["from_id"] == "svc-1"
            assert kwargs["to_id"] == "svc-2"
            assert kwargs["minc"] == 0.7
            assert kwargs["k"] == 2

        session = _fake_trace_session(rows, path_rows=[path_row],
                                      on_path_query=check)
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            # from by exact id, to by case-insensitive name
            body = client.get(
                "/api/v2/trace?from_service=svc-1&to_service=beta"
                "&min_confidence=0.7&k=2&max_hops=4",
                headers=auth_headers).json()
        assert body["from"] == "svc-1"
        assert body["to"] == "svc-2"
        assert len(body["paths"]) == 1
        # F2: the path's confidence compounds — and carries the interval
        # the edge's min/max bounds imply — rather than inheriting the
        # weakest hop's point value.
        confidence = body["paths"][0]["confidence"]
        assert confidence == {"hops": 1, "compounded": 0.9, "lo": 0.8,
                              "hi": 1.0, "weakest_hop": 0.9}
        assert body["paths"][0]["min_confidence"] == 0.8
        assert body["altitude"] == "service"
        assert body["warnings"] == []

    def test_trace_by_exact_name(self, auth_headers):
        rows = _resolve_rows()
        session = _fake_trace_session(rows, path_rows=[])
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            body = client.get(
                "/api/v2/trace?from_service=Alpha&to_service=Beta",
                headers=auth_headers).json()
        assert body["from"] == "svc-1"
        assert body["to"] == "svc-2"
        # no paths -> no_path warning
        assert body["paths"] == []
        assert body["warnings"][0]["kind"] == "no_path"

    def test_trace_altitude_code_attaches_crossings(self, auth_headers):
        rows = _resolve_rows()
        crossing_rows = [{"call_site": "gn-1", "contract": "hc-1"}]
        path_row = {
            "nodes": [{"id": "svc-1", "name": "Alpha", "labels": ["Service"]}],
            "edges": [
                {"type": "CALLS_SERVICE", "confidence": 0.9,
                 "min_confidence": 0.8, "max_confidence": 1.0,
                 "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                 "evidence": [],
                 "evidence_edge_ids": ["src|INVOKES|dst", "bad-ref"]},
                {"type": "CALLS_SERVICE", "confidence": 0.9,
                 "min_confidence": 0.8, "max_confidence": 1.0,
                 "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                 "evidence": [], "evidence_edge_ids": None},
            ],
            "path_min": 0.8,
        }
        # second path with only empty refs -> crossings == []
        path_row2 = {
            "nodes": [{"id": "svc-2", "name": "Beta", "labels": ["Service"]}],
            "edges": [{"type": "CALLS_SERVICE", "confidence": 0.9,
                       "min_confidence": 0.8, "max_confidence": 1.0,
                       "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                       "evidence": [], "evidence_edge_ids": []}],
            "path_min": 0.8,
        }

        def run_side_effect(query, *args, **kwargs):
            res = MagicMock()
            if "MATCH (s:Service) RETURN" in query:
                res.data.return_value = rows
            elif "UNWIND $refs" in query:
                # only called for the path that has valid refs
                assert kwargs["refs"] == [
                    {"src": "src", "type": "INVOKES", "dst": "dst"}]
                res.data.return_value = crossing_rows
            else:
                res.data.return_value = [path_row, path_row2]
            return res

        session = MagicMock()
        session.run.side_effect = run_side_effect
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            body = client.get(
                "/api/v2/trace?from_service=svc-1&to_service=svc-2"
                "&altitude=code",
                headers=auth_headers).json()
        assert body["altitude"] == "code"
        assert body["paths"][0]["crossings"] == crossing_rows
        assert body["paths"][1]["crossings"] == []

    def test_trace_crossing_ref_type_not_allowlisted_skipped(self, auth_headers):
        # Refs carry the edge type; types outside the linker allowlist are
        # dropped before any cypher interpolation (injection guard).
        rows = _resolve_rows()
        path_row = {
            "nodes": [{"id": "svc-1", "name": "Alpha", "labels": ["Service"]}],
            "edges": [{"type": "CALLS_SERVICE", "confidence": 0.9,
                       "min_confidence": 0.8, "max_confidence": 1.0,
                       "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                       "evidence": [],
                       "evidence_edge_ids": ["a|NOT_A_TYPE|b"]}],
            "path_min": 0.8,
        }

        def run_side_effect(query, *args, **kwargs):
            res = MagicMock()
            if "MATCH (s:Service) RETURN" in query:
                res.data.return_value = rows
            elif "UNWIND $refs" in query:
                raise AssertionError("crossing query must not run for "
                                     "non-allowlisted ref types")
            else:
                res.data.return_value = [path_row]
            return res

        session = MagicMock()
        session.run.side_effect = run_side_effect
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            body = client.get(
                "/api/v2/trace?from_service=svc-1&to_service=svc-2"
                "&altitude=code",
                headers=auth_headers).json()
        assert body["paths"][0]["crossings"] == []


class TestAuthMiddleware:
    def test_rate_limiter_window_eviction(self):
        from evigraph.middleware.auth import RateLimiter
        clock = {"t": 100.0}
        with patch("evigraph.middleware.auth.time.monotonic",
                   side_effect=lambda: clock["t"]):
            limiter = RateLimiter(limit=1, window_s=0.01)
            assert limiter.allow("k") is True
            # denied while inside window
            assert limiter.allow("k") is False
            # advance past window -> old hit evicted (line 37-38)
            clock["t"] = 100.5
            assert limiter.allow("k") is True

    def test_audit_swallows_oserror(self):
        from evigraph.middleware.auth import audit
        with patch("evigraph.middleware.auth.open",
                   side_effect=OSError("disk full")), \
             patch("evigraph.middleware.auth.os.makedirs"), \
             patch("evigraph.middleware.auth.logger") as log:
            audit("tid", "POST", "/api/x", 200)
        assert log.error.called

    def test_trace_returns_429_when_rate_limited(self, auth_headers):
        session = MagicMock()
        resolve_result = MagicMock()
        resolve_result.data.return_value = []
        session.run.return_value = resolve_result
        with patch("evigraph.middleware.auth._limiter.allow", return_value=False), \
             patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            response = client.get(
                "/api/v2/trace?from_service=a&to_service=b",
                headers=auth_headers)
        assert response.status_code == 429
        assert response.json()["detail"] == "Rate limit exceeded for trace (30/min)"
        assert response.headers["Retry-After"] == "60"
        # route never ran
        assert session.run.call_count == 0


class TestRateLimitBuckets:
    """A full link run is the most expensive call in the API; before this it
    was the only expensive one with no budget at all."""

    def test_rebuild_has_its_own_tighter_bucket(self):
        from evigraph.middleware.auth import _rate_bucket
        assert _rate_bucket("/api/v2/links/rebuild") == ("rebuild", 4)
        assert _rate_bucket("/api/v2/trace") == ("trace", 30)
        assert _rate_bucket("/api/repos/ingest") == ("ingest", 20)
        assert _rate_bucket("/api/repos") is None

    def test_buckets_are_independent(self):
        from evigraph.middleware.auth import RateLimiter
        limiter = RateLimiter()
        for _ in range(4):
            assert limiter.allow("tok:rebuild", 4) is True
        assert limiter.allow("tok:rebuild", 4) is False
        # Exhausting rebuild must not lock out reads.
        assert limiter.allow("tok:trace", 30) is True

    def test_rebuild_429_after_budget(self, auth_headers):
        from evigraph.middleware.auth import _limiter
        _limiter._hits.clear()
        with patch("evigraph.routes.links.job_queue") as queue:
            queue.submit.return_value = "job-1"
            codes = [client.post("/api/v2/links/rebuild",
                                 headers=auth_headers).status_code
                     for _ in range(6)]
        _limiter._hits.clear()
        assert codes[:4] == [202, 202, 202, 202]
        assert codes[4:] == [429, 429]


class TestTraceHonesty:
    """Design principle 7: an answer states what it cannot see."""

    def test_stale_links_warned_even_when_paths_found(self, auth_headers):
        path_row = {
            "nodes": [{"id": "svc-1", "name": "Alpha", "labels": ["Service"]},
                      {"id": "svc-2", "name": "Beta", "labels": ["Service"]}],
            "edges": [{"type": "CALLS_SERVICE", "confidence": 0.9,
                       "min_confidence": 0.8, "max_confidence": 1.0,
                       "via": [], "weight": 1, "path_prefix": None, "source_repo_id": "repo-a",
                       "evidence": [], "evidence_edge_ids": []}],
            "path_min": 0.8,
        }
        session = _fake_trace_session(
            _resolve_rows(), path_rows=[path_row],
            stale_repos=["org_orders"], failed_partial=2)
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            body = client.get("/api/v2/trace?from_service=svc-1&to_service=svc-2",
                              headers=auth_headers).json()
        kinds = {w["kind"] for w in body["warnings"]}
        assert kinds == {"links_stale", "repos_failed_partial"}
        assert body["paths"]
        stale = next(w for w in body["warnings"] if w["kind"] == "links_stale")
        assert stale["repo_ids"] == ["org_orders"]

    def test_enumeration_is_capped_before_sorting(self, auth_headers):
        captured = {}
        session = _fake_trace_session(
            _resolve_rows(), path_rows=[],
            on_path_query=lambda kw: captured.update(kw))
        with patch("evigraph.routes.trace.get_session",
                   return_value=_session_ctx(session)):
            client.get("/api/v2/trace?from_service=svc-1&to_service=svc-2",
                       headers=auth_headers)
        assert captured["scan_cap"] == 2000
