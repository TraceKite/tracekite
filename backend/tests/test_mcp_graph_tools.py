"""Identity and bounded-graph MCP queries stay precise and deterministic."""

import json
from types import SimpleNamespace

from tracekite.answer import AnswerEnvelope, AnswerStatus, SnapshotIdentity
from tracekite.db.artifact_node_lookup import ArtifactNodeLookup
from tracekite.db.sqlite_store import SQLiteGraphStore
from tracekite.mcp_tools import GraphTools
from tracekite.mcp_server import handle
from tracekite.models.graph_models import GraphNode
from tracekite.node_lookup import InMemoryNodeLookup
from tracekite.status_classify import (
    classify_impact, classify_neighbors, classify_subgraph,
)


def _edge(source: str, target: str, kind: str, confidence: float = 0.9):
    return SimpleNamespace(
        source_id=source, target_id=target, type=kind, status="active",
        confidence=confidence, evidence=[f"{source}.ts:7", f"{target}.ts:3"],
        source_label="Method", target_label="Service",
        detected_by="resolver.http@1", match_type="qualified",
        claim_key=f"http:GET:/{target}", source_repo_id="caller",
        target_repo_id="provider", cross_repo=True,
        extra_props={"min_confidence": 0.8, "max_confidence": confidence,
                     "via": ["http"]},
    )


def _tools() -> GraphTools:
    records = {
        node_id: {"id": node_id, "type": "Method", "name": name,
                  "label": name, "repo_id": "repo", "path": path}
        for node_id, name, path in (
            ("A", "Scene", "src/Scene.ts"),
            ("B", "scene", "src/scene.ts"),
            ("C", "renderScene", "src/render.ts"),
            ("D", "loadScene", "src/load.ts"),
            ("isolated", "Idle", "src/idle.ts"),
        )
    }
    result = SimpleNamespace(
        services=[], rendezvous=[],
        edges=[_edge("A", "B", "INVOKES"),
               _edge("B", "C", "CALLS_SERVICE", 0.95),
               _edge("D", "B", "CONSUMES_FROM", 0.85)],
    )
    return GraphTools(result, node_lookup=InMemoryNodeLookup(records))


class TestIdentity:
    def test_node_describes_layer_zero_identity(self):
        answer = _tools().node("A")

        assert answer["found"] is True
        assert answer["node"] == {
            "id": "A", "type": "Method", "name": "Scene", "label": "Scene",
            "repo_id": "repo", "path": "src/Scene.ts"}

    def test_search_ranks_exact_typed_case_first(self):
        answer = _tools().search("Scene")

        assert [match["id"] for match in answer["matches"][:2]] == ["A", "B"]
        assert answer["matches"][0]["score"] > answer["matches"][1]["score"]

    def test_unknown_node_is_not_reported_as_known_empty(self):
        answer = _tools().node("missing")

        assert answer["found"] is False
        assert answer["reason"] == "node not in graph"


class TestNeighbors:
    def test_direction_and_depth_are_asserted_edge_direction(self):
        tools = _tools()

        outgoing = tools.neighbors("B", direction="out")
        incoming = tools.neighbors("B", direction="in")
        two_hops = tools.neighbors("B", direction="both", depth=2)

        assert [node["id"] for node in outgoing["neighbors"]] == ["C"]
        assert [node["id"] for node in incoming["neighbors"]] == ["A", "D"]
        assert [node["id"] for node in two_hops["neighbors"]] == ["A", "C", "D"]

    def test_edge_filter_and_budget_are_explicit(self):
        answer = _tools().neighbors(
            "B", direction="both", edge_types=["INVOKES"], limit=1)

        assert [node["id"] for node in answer["neighbors"]] == ["A"]
        assert {edge["type"] for edge in answer["edges"]} == {"INVOKES"}
        assert answer["truncated"] is False

        truncated = _tools().neighbors("B", direction="both", limit=1)
        assert truncated["total_neighbors"] == 3
        assert truncated["truncated"] is True

    def test_edges_expose_existing_provenance(self):
        edge = _tools().neighbors("B", direction="out")["edges"][0]

        assert edge["detected_by"] == "resolver.http@1"
        assert edge["match_type"] == "qualified"
        assert edge["via"] == ["http"]
        assert edge["min_confidence"] == 0.8
        assert edge["max_confidence"] == 0.95
        assert edge["cross_repo"] is True
        assert edge["spans"][0]["file"] == "B.ts"

    def test_isolated_and_unknown_nodes_classify_differently(self):
        isolated = _tools().neighbors("isolated")
        unknown = _tools().neighbors("missing")

        assert classify_neighbors(isolated)[0] == AnswerStatus.KNOWN_EMPTY
        assert classify_neighbors(unknown)[0] == AnswerStatus.UNKNOWN_TARGET


class TestSubgraph:
    def test_returns_focus_neighbors_and_induced_edges(self):
        answer = _tools().subgraph("B", depth=1)

        assert [node["id"] for node in answer["nodes"]] == ["B", "A", "C", "D"]
        assert {edge["type"] for edge in answer["edges"]} == {
            "INVOKES", "CALLS_SERVICE", "CONSUMES_FROM"}
        assert answer["truncated"] is False

    def test_edge_budget_sets_truncated_without_hiding_total(self):
        answer = _tools().subgraph("B", depth=1, edge_limit=1)

        assert len(answer["edges"]) == 1
        assert answer["total_edges"] == 3
        assert answer["truncated"] is True

    def test_isolated_subgraph_is_known_empty(self):
        answer = _tools().subgraph("isolated")

        assert classify_subgraph(answer)[0] == AnswerStatus.KNOWN_EMPTY


class TestImpact:
    def test_transitive_dependents_follow_dependency_direction(self):
        answer = _tools().impact("C")

        assert [(row["node_id"], row["distance"]) for row in answer["impacted"]] \
            == [("B", 1), ("A", 2), ("D", 2)]
        assert answer["impacted"][1]["path"][0]["impact_from"] == "C"
        assert answer["impacted"][1]["confidence"]["compounded"] == 0.855

    def test_confidence_filter_and_limit_are_visible(self):
        filtered = _tools().impact("B", min_confidence=0.9)
        truncated = _tools().impact("C", limit=1)

        assert [row["node_id"] for row in filtered["impacted"]] == ["A"]
        assert truncated["total_impacted"] == 3
        assert truncated["truncated"] is True

    def test_isolated_and_unknown_targets_classify_differently(self):
        assert classify_impact(_tools().impact("isolated"))[0] \
            == AnswerStatus.KNOWN_EMPTY
        assert classify_impact(_tools().impact("missing"))[0] \
            == AnswerStatus.UNKNOWN_TARGET


def test_artifact_identity_lookup_does_not_materialize_the_graph(tmp_path):
    path = tmp_path / "repo.tracekite"
    store = SQLiteGraphStore(str(path))
    store.upsert_nodes([GraphNode(
        id="repo:Method:one", repo_id="repo", type="Method", name="buildGraph",
        label="buildGraph", path="src/graph.ts", language="TypeScript",
        start_line=12, end_line=18)])
    store.close()
    lookup = ArtifactNodeLookup([str(path)])

    described = lookup.get("repo:Method:one")
    matches = lookup.search("buildGraph", 5)

    assert described["path"] == "src/graph.ts"
    assert described["start_line"] == 12
    assert [match["id"] for match in matches] == ["repo:Method:one"]


def test_new_protocol_tools_all_validate_as_answer_envelopes():
    tools = _tools()
    tools._snapshot = SnapshotIdentity(engine_version="2.0.0")
    calls = {
        "node": {"node_id": "B"},
        "search": {"query": "scene"},
        "neighbors": {"node_id": "B", "direction": "out"},
        "impact": {"node_id": "C"},
        "subgraph": {"node_id": "B", "depth": 1},
    }

    for request_id, (name, arguments) in enumerate(calls.items(), 1):
        response = handle({
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, tools)
        payload = json.loads(response["result"]["content"][0]["text"])
        envelope = AnswerEnvelope(**payload)
        assert envelope.scope.query_kind == name


def test_query_budget_is_carried_by_the_answer_envelope():
    tools = _tools()
    tools._snapshot = SnapshotIdentity(engine_version="2.0.0")
    response = handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "neighbors", "arguments": {
            "node_id": "B", "direction": "both", "limit": 1}},
    }, tools)
    payload = json.loads(response["result"]["content"][0]["text"])
    envelope = AnswerEnvelope(**payload)

    assert envelope.scope.truncation.truncated is True
    assert envelope.scope.truncation.omitted_count == 2
    assert envelope.scope.truncation.budget == 1
