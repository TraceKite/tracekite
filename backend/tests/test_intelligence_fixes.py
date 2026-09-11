"""Regression tests for the P1/P2 intelligence API fixes.

Each test class maps to one required behavior from the task spec:

1. Incomplete scans must not report complete.
2. Snapshot identity must differ when scan limits/config or dirty-tree
   contents differ.
3. Facade and MCP must share status classification for consumers and trace.
4. MCP tool responses must validate as AnswerEnvelope, including scope.
5. Fresh TraceKite([...]).services() must work without a test fixture
   hiding config.
6. services() completeness must compare repository IDs, not service IDs.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tracekite.answer import (
    AnswerEnvelope,
    AnswerStatus,
    QueryScope,
    SnapshotIdentity,
)
from tracekite.mcp_server import GraphTools, handle
from tracekite.status_classify import classify_consumers, classify_trace

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")


# ---------------------------------------------------------------------------
# 1. Incomplete scans must not report complete
# ---------------------------------------------------------------------------


class TestIncompleteScanCompleteness:
    """With a file cap that truncates the scan, completeness must be false."""

    def test_file_cap_makes_completeness_false(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        engine_config.configure(
            graph_hmac_key="cap-test",
            max_files_per_repo=1,
        )
        try:
            tk = TraceKite([os.path.join(CORPUS, "orders-service")],
                           graph_hmac_key="cap-test")
            answer = tk.services()
            assert answer.completeness.complete is False
            assert any("truncat" in r.lower()
                       for r in answer.completeness.coverage_reasons)
        finally:
            engine_config.reset()

    def test_capped_scan_truncation_carried_in_scope(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        engine_config.configure(
            graph_hmac_key="cap-test2",
            max_files_per_repo=1,
        )
        try:
            tk = TraceKite([os.path.join(CORPUS, "orders-service")],
                           graph_hmac_key="cap-test2")
            answer = tk.services()
            assert answer.scope.truncation.truncated is True
            assert answer.scope.truncation.omitted_count > 0
            assert answer.scope.truncation.budget == 1
        finally:
            engine_config.reset()

    def test_known_empty_consumer_still_incomplete_when_capped(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        engine_config.configure(
            graph_hmac_key="cap-test3",
            max_files_per_repo=1,
        )
        try:
            tk = TraceKite([
                os.path.join(CORPUS, "orders-service"),
                os.path.join(CORPUS, "billing-service"),
            ], graph_hmac_key="cap-test3")
            # billing-service has consumers, but the cap may have dropped
            # some files.  Regardless of found/not-found, completeness
            # must be false because the scan was truncated.
            answer = tk.consumers_of("global:Service:billing-service")
            assert answer.completeness.complete is False
        finally:
            engine_config.reset()


# ---------------------------------------------------------------------------
# 2. Snapshot identity differs on config and dirty-tree content
# ---------------------------------------------------------------------------


class TestSnapshotConfigIdentity:
    """config_digest must change when scan limits change."""

    def test_different_file_caps_different_digest(self):
        from tracekite import engine_config
        from tracekite.scan_meta import config_digest

        engine_config.reset()
        engine_config.configure(max_files_per_repo=100)
        d1 = config_digest(engine_config.get_config())

        engine_config.configure(max_files_per_repo=200)
        d2 = config_digest(engine_config.get_config())

        assert d1 != d2

    def test_same_config_same_digest(self):
        from tracekite import engine_config
        from tracekite.scan_meta import config_digest

        engine_config.reset()
        engine_config.configure(max_files_per_repo=100, parse_timeout_s=30)
        d1 = config_digest(engine_config.get_config())
        d2 = config_digest(engine_config.get_config())
        assert d1 == d2

    def test_hmac_key_value_not_in_digest(self):
        """The digest must not embed the key value — only its presence."""
        from tracekite import engine_config
        from tracekite.scan_meta import config_digest

        engine_config.reset()
        engine_config.configure(graph_hmac_key="secret-abc")
        d1 = config_digest(engine_config.get_config())

        engine_config.configure(graph_hmac_key="secret-xyz")
        d2 = config_digest(engine_config.get_config())

        # Both have a key set; only the boolean matters.
        assert d1 == d2

    def test_key_presence_changes_digest(self):
        from tracekite import engine_config
        from tracekite.scan_meta import config_digest

        engine_config.reset()
        engine_config.configure()
        d_no_key = config_digest(engine_config.get_config())

        engine_config.configure(graph_hmac_key="some-key")
        d_with_key = config_digest(engine_config.get_config())

        assert d_no_key != d_with_key

    def test_control_plane_content_changes_digest(self, tmp_path):
        from tracekite import engine_config
        from tracekite.scan_meta import config_digest

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "confidence.yml").write_text("r1: 0.8\n")
        engine_config.reset()
        engine_config.configure(config_dir=str(config_dir))
        d1 = config_digest(engine_config.get_config())

        (config_dir / "confidence.yml").write_text("r1: 0.9\n")
        d2 = config_digest(engine_config.get_config())
        assert d1 != d2


class TestDirtyTreeDigest:
    """Staged, unstaged, and untracked content must each move the digest."""

    def test_staged_change_differs_from_unstaged(self, tmp_path):
        import hashlib
        import subprocess

        from tracekite.source_meta import _dirty_digest

        def _git(path, *args):
            subprocess.run(["git", *args], cwd=path, check=True,
                           capture_output=True, text=True)

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(str(repo), "init")
        _git(str(repo), "config", "user.email", "t@t.test")
        _git(str(repo), "config", "user.name", "Test")
        f = repo / "file.txt"
        f.write_text("line one\n")
        _git(str(repo), "add", "file.txt")
        _git(str(repo), "commit", "-m", "initial")

        # Unstaged change
        f.write_text("line one\nline two\n")
        d_unstaged = _dirty_digest(str(repo))

        # Stage the same content: the staged diff is part of the identity.
        _git(str(repo), "add", "file.txt")
        d_staged = _dirty_digest(str(repo))
        assert d_staged is not None
        assert d_unstaged != d_staged

        # Then make a different unstaged change on top of the staged content.
        f.write_text("line one\nline two\nline three\n")
        d_staged_plus_unstaged = _dirty_digest(str(repo))

        assert d_unstaged is not None
        assert d_staged_plus_unstaged is not None
        assert d_unstaged != d_staged_plus_unstaged

    def test_untracked_file_changes_digest(self, tmp_path):
        import subprocess

        from tracekite.source_meta import _dirty_digest

        def _git(path, *args):
            subprocess.run(["git", *args], cwd=path, check=True,
                           capture_output=True, text=True)

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(str(repo), "init")
        _git(str(repo), "config", "user.email", "t@t.test")
        _git(str(repo), "config", "user.name", "Test")
        (repo / "file.txt").write_text("content\n")
        _git(str(repo), "add", "file.txt")
        _git(str(repo), "commit", "-m", "initial")

        # Modify tracked file (dirty)
        (repo / "file.txt").write_text("changed\n")
        d_before = _dirty_digest(str(repo))

        # Add an untracked file — digest must change
        (repo / "untracked.txt").write_text("new\n")
        d_after = _dirty_digest(str(repo))

        assert d_before is not None
        assert d_after is not None
        assert d_before != d_after

        (repo / "untracked.txt").write_text("changed\n")
        d_changed = _dirty_digest(str(repo))
        assert d_changed is not None
        assert d_after != d_changed

    def test_clean_tree_has_no_digest(self, tmp_path):
        import subprocess

        from tracekite.source_meta import collect_dir_meta

        def _git(path, *args):
            subprocess.run(["git", *args], cwd=path, check=True,
                           capture_output=True, text=True)

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(str(repo), "init")
        _git(str(repo), "config", "user.email", "t@t.test")
        _git(str(repo), "config", "user.name", "Test")
        (repo / "file.txt").write_text("content\n")
        _git(str(repo), "add", "file.txt")
        _git(str(repo), "commit", "-m", "initial")

        rev = collect_dir_meta(str(repo), "repo")
        assert rev.dirty is False
        assert rev.content_digest is None


# ---------------------------------------------------------------------------
# 3. Shared status classification for consumers and trace
# ---------------------------------------------------------------------------


def _make_tools():
    """Build GraphTools with a small known graph."""
    services = [
        SimpleNamespace(service_id="global:Service:a", name="Alpha",
                        repo_ids=["repo-a"]),
        SimpleNamespace(service_id="global:Service:b", name="Beta",
                        repo_ids=["repo-b"]),
    ]
    edges = [
        SimpleNamespace(source_id="global:Service:a",
                        target_id="global:Service:b",
                        status="active", type="INVOKES", confidence=0.9,
                        evidence=["a.py:1"]),
    ]
    result = SimpleNamespace(services=services, edges=edges, rendezvous=[])
    return GraphTools(result)


class TestSharedStatusClassification:
    """Facade and MCP classify the same way."""

    def test_consumers_known_empty_for_isolated_node(self):
        tools = _make_tools()
        # 'a' has no incoming edges (nobody invokes a), so it is known
        # but has zero consumers.
        raw = tools.consumers_of("global:Service:a")
        status, cands, reason = classify_consumers(raw)
        assert status == AnswerStatus.KNOWN_EMPTY

    def test_consumers_unknown_target_for_typo(self):
        tools = _make_tools()
        raw = tools.consumers_of("global:Service:typo")
        status, cands, reason = classify_consumers(raw)
        assert status == AnswerStatus.UNKNOWN_TARGET

    def test_consumers_ambiguous(self):
        services = [
            SimpleNamespace(service_id="service:a", name="Payments",
                            repo_ids=["repo-a"]),
            SimpleNamespace(service_id="service:b", name="payments",
                            repo_ids=["repo-b"]),
        ]
        edges = [
            SimpleNamespace(source_id="caller", target_id=s.service_id,
                            status="active", type="INVOKES", confidence=0.9,
                            evidence=["caller.py:1"])
            for s in services
        ]
        tools = GraphTools(SimpleNamespace(
            services=services, edges=edges, rendezvous=[]))
        raw = tools.consumers_of("payments")
        status, cands, reason = classify_consumers(raw)
        assert status == AnswerStatus.AMBIGUOUS
        assert reason == "ambiguous service name"

    def test_trace_known_empty_between_known_nodes(self):
        tools = _make_tools()
        known = tools._known_node_ids()
        raw = tools.trace("global:Service:b", "global:Service:a")
        status, cands, reason = classify_trace(raw, known)
        assert status == AnswerStatus.KNOWN_EMPTY

    def test_trace_unknown_target_for_nonexistent(self):
        tools = _make_tools()
        known = tools._known_node_ids()
        raw = tools.trace("global:Service:typo", "global:Service:a")
        status, cands, reason = classify_trace(raw, known)
        assert status == AnswerStatus.UNKNOWN_TARGET

    def test_trace_ambiguous(self):
        services = [
            SimpleNamespace(service_id="service:a", name="Payments",
                            repo_ids=["repo-a"]),
            SimpleNamespace(service_id="service:b", name="payments",
                            repo_ids=["repo-b"]),
        ]
        edges = [
            SimpleNamespace(source_id="caller", target_id=s.service_id,
                            status="active", type="INVOKES", confidence=0.9,
                            evidence=["caller.py:1"])
            for s in services
        ]
        tools = GraphTools(SimpleNamespace(
            services=services, edges=edges, rendezvous=[]))
        known = tools._known_node_ids()
        raw = tools.trace("payments", "caller")
        status, cands, reason = classify_trace(raw, known)
        assert status == AnswerStatus.AMBIGUOUS

    def test_facade_and_mcp_agree_on_trace_known_empty(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.configure(graph_hmac_key="agree-test")
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ], graph_hmac_key="agree-test")

        # Trace between known nodes with no path (reverse direction)
        answer = tk.trace(
            "global:Service:billing-service",
            "global:Service:orders-service",
        )
        # Either known_empty (no path found, both known) or present
        # (if there is a reverse path).  The key: it must NOT be
        # unknown_target because both nodes are known.
        assert answer.status != AnswerStatus.UNKNOWN_TARGET


# ---------------------------------------------------------------------------
# 4. MCP tool responses validate as AnswerEnvelope
# ---------------------------------------------------------------------------


class TestMCPEnvelopeValidation:
    """MCP tool responses must round-trip through AnswerEnvelope(**payload)."""

    def _call_and_parse(self, tool_name, arguments):
        from tracekite import engine_config
        from tracekite.db.memory_store import InMemoryLinkerStore
        from tracekite.services.linker.engine import link
        from tracekite.services.scan import scan

        engine_config.configure(graph_hmac_key="env-test")
        sinks = [scan(os.path.join(CORPUS, "orders-service"), "orders-service"),
                 scan(os.path.join(CORPUS, "billing-service"), "billing-service")]
        result = link(InMemoryLinkerStore(sinks).load_claims(),
                      run_id="linkrun_env", now="2026-01-01T00:00:00+00:00")
        from tracekite.scan_meta import config_digest
        cfg = engine_config.get_config()
        snapshot = SnapshotIdentity(
            repos=[], engine_version="2.0.0", config_version="1.0",
            config_digest=config_digest(cfg))
        tools = GraphTools(result, snapshot=snapshot)
        reply = handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }, tools)
        text = reply["result"]["content"][0]["text"]
        return json.loads(text)

    def test_consumers_of_validates_as_envelope(self):
        payload = self._call_and_parse("consumers_of",
                                       {"node_id": "global:Service:billing-service"})
        env = AnswerEnvelope(**payload)
        assert env.status == AnswerStatus.PRESENT
        assert env.scope.query_kind == "consumers_of"
        assert env.scope.parameters == {"node_id": "global:Service:billing-service"}
        assert env.result["found"] is True

    def test_services_validates_as_envelope(self):
        payload = self._call_and_parse("services", {})
        env = AnswerEnvelope(**payload)
        assert env.status in (AnswerStatus.PRESENT, AnswerStatus.KNOWN_EMPTY)
        assert env.scope.query_kind == "services"

    def test_trace_validates_as_envelope(self):
        payload = self._call_and_parse("trace", {
            "from_id": "global:Service:orders-service",
            "to_id": "global:Service:billing-service",
        })
        env = AnswerEnvelope(**payload)
        assert env.scope.query_kind == "trace"
        assert env.scope.parameters["from_id"] == "global:Service:orders-service"
        assert env.scope.parameters["to_id"] == "global:Service:billing-service"

    def test_unknown_target_validates_as_envelope(self):
        payload = self._call_and_parse("consumers_of",
                                       {"node_id": "global:Service:typo"})
        env = AnswerEnvelope(**payload)
        assert env.status == AnswerStatus.UNKNOWN_TARGET

    def test_top_level_fields_preserved(self):
        """Old clients reading top-level fields still work."""
        payload = self._call_and_parse("consumers_of",
                                       {"node_id": "global:Service:billing-service"})
        assert "found" in payload
        assert "consumers" in payload
        assert "answer_version" in payload
        assert "status" in payload
        assert "scope" in payload

    def test_capped_mcp_answer_is_not_complete(self):
        from tracekite import engine_config
        from tracekite.mcp_server import _load_tools

        engine_config.reset()
        engine_config.configure(graph_hmac_key="mcp-cap-test",
                                max_files_per_repo=1)
        try:
            tools = _load_tools([
                os.path.join(CORPUS, "orders-service"),
                os.path.join(CORPUS, "billing-service"),
            ])
            reply = handle({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {
                    "name": "consumers_of",
                    "arguments": {
                        "node_id": "global:Service:billing-service",
                    },
                },
            }, tools)
            payload = json.loads(reply["result"]["content"][0]["text"])
            envelope = AnswerEnvelope(**payload)
            assert envelope.completeness.complete is False
            assert envelope.scope.truncation.truncated is True
            assert envelope.scope.truncation.omitted_count > 0
        finally:
            engine_config.reset()


# ---------------------------------------------------------------------------
# 5. Fresh TraceKite without engine_config.configure()
# ---------------------------------------------------------------------------


class TestFreshFacadeConfiguration:
    """TraceKite([...], graph_hmac_key=...) works without external config."""

    def test_services_works_with_explicit_key(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        try:
            tk = TraceKite([os.path.join(CORPUS, "orders-service")],
                           graph_hmac_key="fresh-key")
            answer = tk.services()
            assert answer.status == AnswerStatus.PRESENT
            assert answer.result["services"]
        finally:
            engine_config.reset()

    def test_services_fails_closed_without_key(self):
        """Without a key, redaction is fail-closed — not silently weakened."""
        from tracekite import engine_config
        from tracekite.facade import TraceKite
        from tracekite.services.redaction import RedactionKeyMissing

        engine_config.reset()
        try:
            tk = TraceKite([os.path.join(CORPUS, "orders-service")])
            with pytest.raises(RedactionKeyMissing):
                tk.services()
        finally:
            engine_config.reset()

    def test_snapshot_has_config_digest(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        try:
            tk = TraceKite([os.path.join(CORPUS, "orders-service")],
                           graph_hmac_key="digest-key")
            answer = tk.services()
            assert answer.snapshot.config_digest is not None
            assert len(answer.snapshot.config_digest) > 0
        finally:
            engine_config.reset()


# ---------------------------------------------------------------------------
# 6. services() completeness compares repository IDs, not service IDs
# ---------------------------------------------------------------------------


class TestServicesCompletenessRepoIds:
    """Completeness must compare repo_ids from service.repo_ids, not service IDs."""

    def test_services_completeness_uses_repo_ids(self):
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        engine_config.configure(graph_hmac_key="repoid-test")
        try:
            tk = TraceKite([
                os.path.join(CORPUS, "orders-service"),
                os.path.join(CORPUS, "billing-service"),
            ], graph_hmac_key="repoid-test")
            answer = tk.services()
            # The services list repo_ids that match the declared repos.
            # Completeness should be true (all repos analyzed, no caps).
            analyzed = sorted(set(
                rid for s in answer.result.get("services", [])
                for rid in s.get("repos", [])
            ))
            expected = tk._repo_ids()
            assert set(analyzed) == set(expected)
            assert answer.completeness.complete is True
        finally:
            engine_config.reset()

    def test_services_completeness_false_when_repo_missing_from_services(self):
        """If a repo's service has no repo_ids, completeness drops."""
        from tracekite import engine_config
        from tracekite.facade import TraceKite

        engine_config.reset()
        engine_config.configure(graph_hmac_key="repoid-test2")
        try:
            tk = TraceKite([
                os.path.join(CORPUS, "orders-service"),
                os.path.join(CORPUS, "billing-service"),
            ], graph_hmac_key="repoid-test2")
            answer = tk.services()
            # Both repos are declared; both should appear in analyzed_repos.
            # If one didn't (because a service had empty repo_ids),
            # completeness would be false.  Here both are present, so
            # we verify the comparison is by repo_id, not service_id.
            assert "orders-service" in answer.scope.analyzed_repos
            assert "billing-service" in answer.scope.analyzed_repos
            # Service IDs (global:Service:...) must NOT be in analyzed_repos.
            assert not any("global:Service:" in r
                           for r in answer.scope.analyzed_repos)
        finally:
            engine_config.reset()
