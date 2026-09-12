"""Tests for the framework integration facade."""

import os

import pytest

from tracekite import engine_config
from tracekite.answer import AnswerStatus, FreshnessState
from tracekite.facade import TraceKite

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")


@pytest.fixture(scope="module", autouse=True)
def _configure():
    engine_config.configure(graph_hmac_key="facade-test")


class TestFacadeServices:
    def test_services_returns_present_with_snapshot(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        answer = tk.services()
        assert answer.status == AnswerStatus.PRESENT
        assert answer.result["services"]
        assert answer.snapshot.engine_version == "2.0.0"
        assert answer.freshness == FreshnessState.UNKNOWN

    def test_services_snapshot_has_revisions(self):
        tk = TraceKite([os.path.join(CORPUS, "orders-service")])
        answer = tk.services()
        assert len(answer.snapshot.repos) == 1
        rev = answer.snapshot.repos[0]
        assert rev.repo_id == "orders-service"
        # Corpus directories have no .git, so they are unversioned
        assert rev.unversioned is True
        assert rev.head_sha is None

    def test_services_completeness_carried(self):
        tk = TraceKite([os.path.join(CORPUS, "orders-service")])
        answer = tk.services()
        assert answer.completeness is not None
        assert answer.completeness.safe_to_delete is False


class TestFacadeConsumersOf:
    def test_present_consumer(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        answer = tk.consumers_of("global:Service:billing-service")
        assert answer.status == AnswerStatus.PRESENT
        assert answer.result["found"] is True
        assert answer.result["consumers"]

    def test_known_empty_for_isolated_node(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        # A service that exists but has no consumers
        answer = tk.consumers_of("global:Service:orders-service")
        assert answer.status in (AnswerStatus.PRESENT,
                                 AnswerStatus.KNOWN_EMPTY)
        assert answer.completeness.safe_to_delete is False

    def test_unknown_target_for_typo(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        answer = tk.consumers_of("global:Service:typo-service")
        assert answer.status == AnswerStatus.UNKNOWN_TARGET
        assert answer.candidates

    def test_ambiguous_name_declined(self):
        from types import SimpleNamespace
        from tracekite.facade import TraceKite
        # Use the existing test pattern from test_mcp_server
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
        from tracekite.mcp_server import GraphTools
        from tracekite.answer import SnapshotIdentity
        tools = GraphTools(
            SimpleNamespace(services=services, edges=edges, rendezvous=[]),
            snapshot=SnapshotIdentity(engine_version="2.0.0"),
        )
        tk = TraceKite.__new__(TraceKite)
        tk._tools = tools
        tk._snapshot = tools._snapshot
        tk._paths = []
        answer = tk.consumers_of("payments")
        assert answer.status == AnswerStatus.AMBIGUOUS
        assert answer.reason == "ambiguous service name"


class TestFacadeTrace:
    def test_trace_finds_path(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        answer = tk.trace(
            "global:Service:orders-service",
            "global:Service:billing-service",
        )
        assert answer.status == AnswerStatus.PRESENT
        assert answer.result["found"] is True
        assert answer.result["paths"]


class TestFacadeDeprecations:
    def test_deprecations_returns_present(self):
        tk = TraceKite([
            os.path.join(CORPUS, "orders-service"),
            os.path.join(CORPUS, "billing-service"),
        ])
        answer = tk.deprecations()
        assert answer.status == AnswerStatus.PRESENT
        assert "contracts" in answer.result
