"""Integration tests against the live Neo4j: invariants the design CI-asserts.

Covers: typed edges only (zero RELATES_TO), write reconciliation, edge dedupe,
lite-tier defaults applied on read, repo-scoped clears, job persistence.
"""

import pytest

from evigraph.db.constraints import clear_repo_graph, create_constraints
from evigraph.db.neo4j_client import get_session
from evigraph.services import graph_factories as gf
from evigraph.services import graph_writer
from evigraph.services.graph_reader import get_graph, get_node_details, get_repo
from evigraph.services.graph_writer import WriteReconciliationError
from evigraph.services.redaction import redact
from tests.conftest import neo4j_available

pytestmark = pytest.mark.skipif(not neo4j_available(),
                                reason="Neo4j is not reachable")

REPO_A = "testint-repo-a"
REPO_B = "testint-repo-b"


def _build_repo_a():
    nodes = [gf.create_repo_node(REPO_A, "t", "alpha",
                                 "https://github.com/t/alpha", "main",
                                 "sha-a", {"Python": 2})]
    folder = gf.create_folder_node(REPO_A, "src")
    file_a = gf.create_file_node(REPO_A, "src/a.py", "a.py", "Python", 100, False)
    file_b = gf.create_file_node(REPO_A, "src/b.py", "b.py", "Python", 100, False)
    nodes += [folder, file_a, file_b]

    from evigraph.models.graph_models import GraphNode
    from evigraph.utils.hashing import build_symbol_uid, generate_node_id, symbol_extra
    caller = GraphNode(
        id=generate_node_id(REPO_A, "Function", "src/a.py", "caller",
                            extra=symbol_extra("caller", 0, 0)),
        repo_id=REPO_A, type="Function", name="caller", label="caller",
        path="src/a.py", language="Python", start_line=1, end_line=4,
        symbol_uid=build_symbol_uid(REPO_A, "python", "src/a.py", "caller", 0),
        extra_props={"arity": 0},
    )
    callee = GraphNode(
        id=generate_node_id(REPO_A, "Function", "src/b.py", "callee",
                            extra=symbol_extra("callee", 0, 0)),
        repo_id=REPO_A, type="Function", name="callee", label="callee",
        path="src/b.py", language="Python", start_line=1, end_line=4,
        symbol_uid=build_symbol_uid(REPO_A, "python", "src/b.py", "callee", 0),
        extra_props={"arity": 0},
    )
    endpoint = gf.create_endpoint_node(REPO_A, "src/a.py", "Python", "GET",
                                       "/things/{id}", "fastapi", "caller",
                                       "", 1)
    dep = gf.create_dependency_node(REPO_A, "fastapi", "0.110", "prod", "pip",
                                    "requirements.txt")
    config = gf.create_config_node(REPO_A, "app.yml", "DB_PASSWORD",
                                   redact("DB_PASSWORD", "int-test-secret-value"))
    nodes += [caller, callee, endpoint, dep, config]

    edges = [
        gf.create_contains_edge(REPO_A, REPO_A, folder.id),
        gf.create_contains_edge(REPO_A, folder.id, file_a.id),
        gf.create_contains_edge(REPO_A, folder.id, file_b.id),
        gf.create_declares_edge(REPO_A, file_a.id, caller.id, "function"),
        gf.create_declares_edge(REPO_A, file_b.id, callee.id, "function"),
        gf.create_calls_edge(REPO_A, caller.id, callee.id, 0.9, ["src/a.py:3"]),
        gf.create_exposes_api_edge(REPO_A, caller.id, endpoint.id, ["src/a.py:1"]),
        gf.create_depends_on_edge(REPO_A, file_a.id, dep.id, ["requirements.txt"]),
        gf.create_declares_edge(REPO_A, file_a.id, config.id, "config"),
    ]
    return nodes, edges, caller, callee, file_a


@pytest.fixture(scope="module")
def seeded_graph():
    create_constraints()
    clear_repo_graph(REPO_A)
    clear_repo_graph(REPO_B)
    nodes, edges, caller, callee, file_a = _build_repo_a()
    written_nodes = graph_writer.write_nodes_batch(nodes)
    written_edges = graph_writer.write_edges_batch(edges)
    yield {"nodes": nodes, "edges": edges, "caller": caller, "callee": callee,
           "file_a": file_a, "written_nodes": written_nodes,
           "written_edges": written_edges}
    clear_repo_graph(REPO_A)
    clear_repo_graph(REPO_B)


class TestWriteInvariants:
    def test_counts_reconcile(self, seeded_graph):
        assert seeded_graph["written_nodes"] == len(seeded_graph["nodes"])
        assert sum(seeded_graph["written_edges"].values()) == \
            len(seeded_graph["edges"])

    def test_store_has_zero_relates_to(self, seeded_graph):
        with get_session() as session:
            count = session.run(
                "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS c"
            ).single()["c"]
        assert count == 0

    def test_typed_edges_present(self, seeded_graph):
        with get_session() as session:
            result = session.run(
                "MATCH (a:GraphNode {repo_id: $repo})-[r]->(b) "
                "RETURN type(r) AS t, count(r) AS c", repo=REPO_A,
            )
            counts = {record["t"]: record["c"] for record in result}
        assert counts["CONTAINS"] == 3
        assert counts["DECLARES"] == 3
        assert counts["CALLS"] == 1
        assert counts["EXPOSES_API"] == 1
        assert counts["DEPENDS_ON"] == 1

    def test_missing_endpoint_fails_loudly(self, seeded_graph):
        bad_edge = gf.create_calls_edge(REPO_A, "nonexistent-node-id",
                                        seeded_graph["callee"].id, 0.9,
                                        ["ghost.py:1"])
        with pytest.raises(WriteReconciliationError):
            graph_writer.write_edges_batch([bad_edge])

    def test_duplicate_edge_merges_not_duplicates(self, seeded_graph):
        duplicate = gf.create_calls_edge(REPO_A, seeded_graph["caller"].id,
                                         seeded_graph["callee"].id, 0.9,
                                         ["src/a.py:3"])
        graph_writer.write_edges_batch([duplicate])
        with get_session() as session:
            count = session.run(
                "MATCH (:GraphNode {id: $a})-[r:CALLS]->(:GraphNode {id: $b}) "
                "RETURN count(r) AS c",
                a=seeded_graph["caller"].id, b=seeded_graph["callee"].id,
            ).single()["c"]
        assert count == 1

    def test_no_raw_secret_in_store(self, seeded_graph):
        with get_session() as session:
            count = session.run(
                "MATCH (n:GraphNode {repo_id: $repo}) "
                "WITH n, [k IN keys(n) | toString(n[k])] AS vals "
                "WHERE any(v IN vals WHERE v CONTAINS 'int-test-secret-value') "
                "RETURN count(n) AS c", repo=REPO_A,
            ).single()["c"]
        assert count == 0


class TestReaderContracts:
    def test_lite_defaults_applied_on_read(self, seeded_graph):
        detail = get_node_details(REPO_A, seeded_graph["file_a"].id)
        assert detail is not None
        contains_row = next(r for r in detail.incoming
                            if r["relationship"] == "CONTAINS")
        assert contains_row["confidence"] == 1.0
        assert contains_row["origin"] == "extracted"

    def test_calls_edge_provenance_via_reader(self, seeded_graph):
        detail = get_node_details(REPO_A, seeded_graph["caller"].id)
        calls_row = next(r for r in detail.outgoing
                         if r["relationship"] == "CALLS")
        assert calls_row["confidence"] == 0.9
        assert calls_row["origin"] == "inferred"
        assert calls_row["evidence"] == ["src/a.py:3"]

    def test_get_graph_returns_typed_links(self, seeded_graph):
        response = get_graph(REPO_A, view="overview")
        assert response.stats.total_nodes > 0
        types = {link.type for link in response.links}
        assert "RELATES_TO" not in types
        assert all(isinstance(link.confidence, float)
                   for link in response.links)

    def test_repo_summary_promoted_props(self, seeded_graph):
        summary = get_repo(REPO_A)
        assert summary is not None
        assert summary.owner == "t"
        assert summary.head_commit_sha == "sha-a"
        assert summary.github_url == "https://github.com/t/alpha"


class TestRepoScopedLifecycle:
    def test_clear_is_repo_scoped(self, seeded_graph):
        node_b = gf.create_repo_node(REPO_B, "t", "beta",
                                     "https://github.com/t/beta", "main",
                                     "sha-b", {})
        graph_writer.write_nodes_batch([node_b])
        clear_repo_graph(REPO_B)
        with get_session() as session:
            remaining_a = session.run(
                "MATCH (n:GraphNode {repo_id: $repo}) RETURN count(n) AS c",
                repo=REPO_A,
            ).single()["c"]
            remaining_b = session.run(
                "MATCH (n:GraphNode {repo_id: $repo}) RETURN count(n) AS c",
                repo=REPO_B,
            ).single()["c"]
        assert remaining_a > 0
        assert remaining_b == 0

    def test_lifecycle_state_guard(self, seeded_graph):
        with pytest.raises(ValueError):
            graph_writer.set_repo_lifecycle(REPO_A, "bogus-state")
        graph_writer.set_repo_lifecycle(REPO_A, "ingested")
        summary = get_repo(REPO_A)
        assert summary.lifecycle_state == "ingested"

    def test_job_persistence_roundtrip(self, seeded_graph):
        graph_writer.create_or_update_job("testint-job-1", REPO_A, "running",
                                          40, "half way")
        with get_session() as session:
            record = session.run(
                "MATCH (j:IngestionJob {id: $jid}) "
                "RETURN j.status AS status, j.progress AS progress",
                jid="testint-job-1",
            ).single()
        assert record["status"] == "running"
        assert record["progress"] == 40
