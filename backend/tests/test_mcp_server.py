"""An agent queries the graph over MCP.

The exit criterion is run literally: the real server process is driven
over stdio with the protocol's own frames — initialize, tools/list,
tools/call — and the answers carry the same evidence discipline as every
other surface. A hand-rolled transport earns its keep only if the
protocol conversation actually works, so that is what the e2e pins.
"""

import json
import os
import subprocess
import sys
from io import StringIO
from types import SimpleNamespace

import pytest

from adduce import engine_config
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.mcp_server import GraphTools, _collect_claims, handle, serve
from adduce.services.linker.engine import link
from adduce.services.linker.traverse import find_paths
from adduce.services.scan import scan

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "corpus")
BACKEND = os.path.join(os.path.dirname(__file__), "..")


def linked():
    engine_config.configure(graph_hmac_key="mcp-test")
    sinks = [scan(os.path.join(CORPUS, "orders-service"), "orders-service"),
             scan(os.path.join(CORPUS, "billing-service"),
                  "billing-service")]
    return link(InMemoryLinkerStore(sinks).load_claims(),
                run_id="linkrun_mcp", now="2026-01-01T00:00:00+00:00")


class TestTraverse:
    def test_shortest_paths_come_first_and_are_deterministic(self):
        result = linked()
        paths = find_paths(result.edges, "global:Service:orders-service",
                           "global:Service:billing-service")
        assert paths, "the corpus's flagship connection must trace"
        assert len(paths[0]) == 1
        again = find_paths(result.edges, "global:Service:orders-service",
                           "global:Service:billing-service")
        assert paths == again

    def test_a_candidate_edge_carries_no_path(self):
        result = linked()
        for edge in result.edges:
            edge.status = "candidate"
        assert find_paths(result.edges, "global:Service:orders-service",
                          "global:Service:billing-service") == []


class TestProtocol:
    def test_unknown_tool_and_method_are_errors_not_crashes(self):
        tools = GraphTools(linked())
        bad_tool = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "drop_tables"}}, tools)
        assert bad_tool["error"]["code"] == -32602
        bad_method = handle({"jsonrpc": "2.0", "id": 2,
                             "method": "resources/list"}, tools)
        assert bad_method["error"]["code"] == -32601

    def test_unknown_node_returns_candidates_not_an_empty_list(self):
        tools = GraphTools(linked())
        answer = tools.consumers_of("global:Service:typo")
        assert answer["found"] is False
        assert answer["candidates"], (
            '"nobody depends on it" is the one wrong answer for a typo')

    def test_non_object_request_is_a_protocol_error(self):
        answer = handle([], GraphTools(linked()))

        assert answer["error"] == {
            "code": -32600, "message": "invalid request"}

    def test_non_string_node_id_is_an_argument_error(self):
        answer = handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "consumers_of", "arguments": {"node_id": 4}},
        }, GraphTools(linked()))

        assert answer["error"] == {
            "code": -32602, "message": "node id must be a string"}

    def test_ambiguous_friendly_name_is_declined(self):
        services = [
            SimpleNamespace(service_id="service:a", name="Payments",
                            repo_ids=["repo-a"]),
            SimpleNamespace(service_id="service:b", name="payments",
                            repo_ids=["repo-b"]),
        ]
        edges = [
            SimpleNamespace(source_id="caller", target_id=service.service_id,
                            status="active", type="INVOKES", confidence=0.9,
                            evidence=["caller.py:1"])
            for service in services
        ]
        tools = GraphTools(SimpleNamespace(
            services=services, edges=edges, rendezvous=[]))

        consumers = tools.consumers_of("payments")
        traced = tools.trace("payments", "caller")

        assert consumers["found"] is False
        assert consumers["reason"] == "ambiguous service name"
        assert consumers["candidates"] == ["service:a", "service:b"]
        assert traced["found"] is False
        assert traced["candidates"]["from"] == ["service:a", "service:b"]

    def test_services_exclude_unbacked_virtual_names(self):
        result = SimpleNamespace(
            services=[
                SimpleNamespace(service_id="service:a", name="A",
                                repo_ids=["repo-a"]),
                SimpleNamespace(service_id="service:virtual", name="Virtual",
                                repo_ids=[]),
            ],
            edges=[],
            rendezvous=[],
        )

        assert GraphTools(result).services()["services"] == [
            {"id": "service:a", "name": "A", "repos": ["repo-a"]}]

    def test_known_node_with_no_consumers_is_not_reported_unknown(self):
        result = SimpleNamespace(
            services=[],
            edges=[SimpleNamespace(
                source_id="source-only", target_id="target",
                status="active", type="INVOKES", confidence=0.9,
                evidence=["caller.py:1"])],
            rendezvous=[],
        )

        answer = GraphTools(result).consumers_of("source-only")

        assert answer == {
            "found": True, "node_id": "source-only", "consumers": []}

    def test_repository_backed_service_without_edges_is_known(self):
        result = SimpleNamespace(
            services=[SimpleNamespace(
                service_id="service:idle", name="Idle", repo_ids=["repo-a"])],
            edges=[],
            rendezvous=[],
        )

        answer = GraphTools(result).consumers_of("Idle")

        assert answer == {
            "found": True, "node_id": "service:idle", "consumers": []}

    def test_trace_rejects_out_of_contract_hop_limit(self):
        with pytest.raises(ValueError, match="between 1 and 8"):
            GraphTools(linked()).trace("a", "b", max_hops=9)

    def test_consumers_carry_derived_spans_and_services_carry_commits(self):
        # F4 at the boundary: strings stay the record (§3.1); structure is
        # derived where an agent deep-links. Commits map per repo — never
        # per span, which would be invented attribution.
        tools = GraphTools(linked(), commits={"orders-service": "abc123"})
        assert tools.services()["commits"] == {"orders-service": "abc123"}
        result = linked()
        target = next(e.target_id for e in result.edges
                      if e.status == "active" and e.evidence)
        answer = tools.consumers_of(target)
        spans = [s for c in answer["consumers"] for s in c["spans"]]
        assert spans and all(s["file"] for s in spans)
        for consumer in answer["consumers"]:
            assert len(consumer["spans"]) == len(consumer["evidence"])


class TestEndToEnd:
    def test_an_agent_conversation_over_stdio(self, tmp_path):
        """The exit criterion, literally: artifacts in, protocol frames
        exchanged, an evidence-cited answer out."""
        engine_config.configure(graph_hmac_key="mcp-e2e")
        from adduce.db.artifact import write_artifact

        paths = [write_artifact(
            scan(os.path.join(CORPUS, name), name), name, str(tmp_path)).path
            for name in ("orders-service", "billing-service")]

        frames = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "consumers_of", "arguments": {
                 "node_id": "global:Service:billing-service"}}},
        ]
        proc = subprocess.run(
            [sys.executable, "-m", "adduce.cli", "mcp", *paths],
            input="\n".join(json.dumps(f) for f in frames) + "\n",
            cwd=BACKEND, capture_output=True, text=True, timeout=300,
            env={**os.environ, "GRAPH_HMAC_KEY": "mcp-e2e"})
        assert proc.returncode == 0, proc.stderr
        replies = [json.loads(line) for line in
                   proc.stdout.strip().splitlines()]

        by_id = {r["id"]: r for r in replies}
        assert by_id[1]["result"]["protocolVersion"] == "2024-11-05"
        names = {t["name"] for t in by_id[2]["result"]["tools"]}
        assert {"services", "consumers_of", "trace",
                "deprecations"} <= names
        answer = json.loads(by_id[3]["result"]["content"][0]["text"])
        assert answer["found"] is True
        assert any("billing_client.py" in cite
                   for c in answer["consumers"] for cite in c["evidence"])
        # The notification produced no reply — three frames had ids,
        # three replies came back.
        assert len(replies) == 3

    def test_source_directory_is_scanned_before_serving(self):
        stdin = StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1,
                        "method": "tools/list"}) + "\n")
        stdout = StringIO()

        assert serve([os.path.join(CORPUS, "orders-service")],
                     stdin=stdin, stdout=stdout) == 0
        reply = json.loads(stdout.getvalue())
        assert reply["id"] == 1
        assert reply["result"]["tools"]


class TestInputs:
    def test_source_claims_use_the_scan_adapter(self):
        claims, commits = [], {}

        _collect_claims(os.path.join(CORPUS, "orders-service"),
                        claims, commits)

        assert claims
        assert commits == {"orders-service": ""}

    def test_duplicate_repository_inputs_are_rejected(self):
        path = os.path.join(CORPUS, "orders-service")
        claims, commits = [], {}
        _collect_claims(path, claims, commits)

        with pytest.raises(ValueError, match="duplicate repository"):
            _collect_claims(path, claims, commits)

    def test_missing_input_is_rejected(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _collect_claims(str(tmp_path / "missing"), [], {})
