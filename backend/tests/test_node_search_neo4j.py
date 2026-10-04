"""Search ranks the exact definition first, against the live Neo4j."""

import pytest

from tracekite.db.constraints import clear_repo_graph, create_constraints
from tracekite.models.graph_models import GraphNode
from tracekite.services import graph_writer
from tracekite.services.node_search import search_nodes
from tests.conftest import neo4j_available

pytestmark = pytest.mark.skipif(not neo4j_available(),
                                reason="Neo4j is not reachable")

REPO = "testint-search"


def _node(kind, name, path):
    return GraphNode(id=f"{REPO}:{kind}:{name}:{path}", repo_id=REPO, type=kind,
                     name=name, label=name, path=path, language="TypeScript")


@pytest.fixture(scope="module", autouse=True)
def estate():
    create_constraints()
    clear_repo_graph(REPO)
    # Forty matches that merely contain the word, written first so that an
    # unordered LIMIT would return them and nothing else — the excalidraw case.
    noise = [_node("Method", f"updateScene{i:02d}", "renderer/scene.ts")
             for i in range(40)]
    noise += [_node("File", f"util{i}.ts", f"packages/scene/util{i}.ts")
              for i in range(10)]
    wanted = [_node("Class", "Scene", "element/Scene.ts"),
              _node("File", "Scene.ts", "element/Scene.ts"),
              _node("Interface", "SceneStateCallback", "element/Scene.ts")]
    graph_writer.write_nodes_batch(noise + wanted)
    yield
    clear_repo_graph(REPO)


def test_the_exact_definition_comes_first():
    results = search_nodes(REPO, "Scene", limit=5)

    assert (results[0].type, results[0].label) == ("Class", "Scene")


def test_prefix_matches_follow_shortest_first():
    labels = [r.label for r in search_nodes(REPO, "Scene", limit=5)]

    assert labels[1:3] == ["Scene.ts", "SceneStateCallback"]


def test_path_only_matches_come_last_and_score_lowest():
    results = search_nodes(REPO, "scene", limit=100)
    path_only = [r for r in results if "scene" not in r.label.lower()]

    assert path_only and results[-len(path_only):] == path_only
    assert max(r.score for r in path_only) < min(
        r.score for r in results if r not in path_only)


def test_matching_ignores_case():
    assert search_nodes(REPO, "sCeNe", limit=1)[0].label == "Scene"
