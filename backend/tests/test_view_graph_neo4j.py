"""A view's context follows only the edges it draws, against the live Neo4j."""

import pytest

from tracekite.db.constraints import clear_repo_graph, create_constraints
from tracekite.models.graph_models import GraphEdge, GraphNode
from tracekite.services import graph_writer
from tracekite.services.graph_reader import get_graph
from tests.conftest import neo4j_available

pytestmark = pytest.mark.skipif(not neo4j_available(),
                                reason="Neo4j is not reachable")

REPO = "testint-view"
ENDPOINTS = 4
# Room for every endpoint and its handler, so what is left to show is
# whether anything else is pulled in around them.
LIMIT = 2 * ENDPOINTS


def _node(kind, name, path="src/app.controller.ts"):
    return GraphNode(id=f"{REPO}:{kind}:{name}", repo_id=REPO, type=kind,
                     name=name, label=name, path=path, language="TypeScript")


def _edge(kind, source, target):
    return GraphEdge(source_id=source.id, target_id=target.id, repo_id=REPO,
                     type=kind, label=kind.lower())


@pytest.fixture(scope="module", autouse=True)
def estate():
    """Endpoints, the handlers that expose them, and the evidence claims
    that cite each endpoint — the shape nest and immich ingest into."""
    create_constraints()
    clear_repo_graph(REPO)
    source = _node("File", "app.controller.ts")
    nodes, edges = [source], []
    for i in range(ENDPOINTS):
        handler = _node("Method", f"handler{i:02d}")
        endpoint = _node("ApiEndpoint", f"GET /r{i:02d}")
        claim = _node("ContractClaim", f"http:GET:/r{i:02d}")
        nodes += [handler, endpoint, claim]
        edges += [_edge("DECLARES", source, handler),
                  _edge("EXPOSES_API", handler, endpoint),
                  _edge("EVIDENCED_BY", claim, endpoint)]
    graph_writer.write_nodes_batch(nodes)
    graph_writer.write_edges_batch(edges)
    yield
    clear_repo_graph(REPO)


def test_evidence_claims_are_not_pulled_in_as_parents():
    graph = get_graph(REPO, view="api", limit=LIMIT)

    assert "ContractClaim" not in {node.type for node in graph.nodes}


def test_no_returned_node_is_an_orphan():
    # EVIDENCED_BY is not a view edge, so a claim pulled in as a "parent"
    # arrived with nothing drawn to it.
    graph = get_graph(REPO, view="api", limit=LIMIT)

    touched = {end for link in graph.links for end in (link.source, link.target)}
    assert {node.id for node in graph.nodes} <= touched
