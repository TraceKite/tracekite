"""Regression tests for the remaining release-blocking contract bugs."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

from tracekite import engine_config
from tracekite.answer import AnswerEnvelope, AnswerStatus, SnapshotIdentity
from tracekite.db.artifact import write_artifact
from tracekite.facade import TraceKite
from tracekite.mcp_envelope import wrap_answer
from tracekite.mcp_server import GraphTools
from tracekite.services.scan import scan
from tracekite.status_classify import classify_trace

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")


def _artifact(tmp_path, cap: int):
    engine_config.configure(
        graph_hmac_key="artifact-regression",
        max_files_per_repo=cap,
    )
    sink = scan(os.path.join(CORPUS, "orders-service"), "orders-service")
    return write_artifact(
        sink,
        "orders-service",
        str(tmp_path),
        head_sha="same-commit",
    )


class TestArtifactSnapshotAndCoverage:
    def test_artifact_coverage_survives_facade_load(self, tmp_path):
        try:
            ref = _artifact(tmp_path, cap=1)
            engine_config.configure(max_files_per_repo=50_000)

            answer = TraceKite(
                [ref.path], graph_hmac_key="artifact-regression"
            ).services()

            assert answer.completeness.complete is False
            assert answer.scope.truncation.truncated is True
            assert answer.scope.truncation.omitted_count > 0
            assert any("cap" in reason for reason in
                       answer.completeness.coverage_reasons)
        finally:
            engine_config.reset()

    def test_artifact_bytes_and_producer_are_in_snapshot(self, tmp_path):
        try:
            capped = _artifact(tmp_path / "capped", cap=1)
            full = _artifact(tmp_path / "full", cap=50_000)
            assert capped.digest != full.digest

            engine_config.configure(max_files_per_repo=50_000)
            capped_answer = TraceKite(
                [capped.path], graph_hmac_key="artifact-regression"
            ).services()
            full_answer = TraceKite(
                [full.path], graph_hmac_key="artifact-regression"
            ).services()

            capped_revision = capped_answer.snapshot.repos[0]
            full_revision = full_answer.snapshot.repos[0]
            assert capped_revision.content_digest == capped.digest
            assert full_revision.content_digest == full.digest
            assert capped_revision.producer["wire_version"]
            assert capped_revision.producer["engine_version"] == "2.0.0"
            assert capped_revision.producer["max_files_per_repo"] == 1
            assert full_revision.producer["max_files_per_repo"] == 50_000
            assert (capped_answer.snapshot.canonical_digest() !=
                    full_answer.snapshot.canonical_digest())
        finally:
            engine_config.reset()

    def test_cached_answer_keeps_load_budget(self):
        try:
            engine_config.configure(
                graph_hmac_key="cache-regression",
                max_files_per_repo=1,
            )
            tk = TraceKite(
                [os.path.join(CORPUS, "orders-service")],
                graph_hmac_key="cache-regression",
            )
            first = tk.services()

            engine_config.configure(max_files_per_repo=50_000)
            second = tk.services()

            assert first.scope.truncation.budget == 1
            assert second.scope.truncation.budget == 1
            assert (first.snapshot.canonical_digest() ==
                    second.snapshot.canonical_digest())
        finally:
            engine_config.reset()

    def test_artifact_coverage_survives_mcp_load(self, tmp_path):
        from tracekite.mcp_server import _load_tools, handle

        try:
            ref = _artifact(tmp_path, cap=1)
            engine_config.configure(max_files_per_repo=50_000)
            tools = _load_tools([ref.path])
            reply = handle({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "services",
                    "arguments": {},
                },
            }, tools)
            payload = json.loads(reply["result"]["content"][0]["text"])
            envelope = AnswerEnvelope(**payload)

            assert envelope.completeness.complete is False
            assert envelope.scope.truncation.truncated is True
        finally:
            engine_config.reset()


class TestEnvelopeAndStatusRegression:
    def test_ambiguous_trace_envelope_keeps_list_candidates(self):
        snapshot = SnapshotIdentity(
            engine_version="2.0.0",
            config_version="producer-config",
            config_digest="config-digest",
        )
        raw = {
            "from": "payments",
            "to": "caller",
            "paths": [],
            "found": False,
            "reason": "ambiguous service name",
            "candidates": {"from": ["service:a", "service:b"], "to": []},
        }

        payload = wrap_answer(raw, "trace", {
            "from_id": "payments",
            "to_id": "caller",
        }, snapshot)
        envelope = AnswerEnvelope(**payload)

        assert envelope.candidates == ["service:a", "service:b"]
        assert envelope.snapshot.config_version == "producer-config"
        assert isinstance(payload["candidates"], list)

    def test_resolved_service_names_are_known_when_path_is_empty(self):
        services = [
            SimpleNamespace(
                service_id="global:Service:a", name="Alpha", repo_ids=["repo-a"]
            ),
            SimpleNamespace(
                service_id="global:Service:b", name="Beta", repo_ids=["repo-b"]
            ),
        ]
        edges = [
            SimpleNamespace(
                source_id="global:Service:a",
                target_id="global:Service:b",
                status="active",
                type="INVOKES",
                confidence=0.9,
                evidence=["a.py:1"],
            )
        ]
        tools = GraphTools(SimpleNamespace(
            services=services, edges=edges, rendezvous=[]))

        raw = tools.trace("BETA", "ALPHA")
        status, _, reason = classify_trace(raw, tools._known_node_ids())

        assert status == AnswerStatus.KNOWN_EMPTY
        assert reason == "no path between known nodes"
