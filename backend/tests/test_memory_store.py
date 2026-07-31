"""Every GraphStore backend, against the same assertions.

These pin the behaviours every other backend must match. A SQLite or Neo4j
implementation that disagrees with any assertion here is wrong, because the
protocol is the contract and this is its first implementation.
"""

import os

import pytest

from adduce.db.graph_store import Aggregate, BoundedPath, Neighbourhood
from adduce.db.memory_store import InMemoryGraphStore, InMemoryLinkerStore
from adduce.db.sqlite_store import SQLiteGraphStore
from adduce.models.graph_models import GraphEdge, GraphNode


def node(nid, ntype="File", repo="r1"):
    return GraphNode(id=nid, repo_id=repo, type=ntype, name=nid, label=nid)


def edge(src, dst, etype="CALLS_SERVICE", repo="r1"):
    """A linker edge, with the provenance the write path demands.

    `created_by`, `detected_by` and `link_run_id` are not decoration: the
    Neo4j writer rejects a linker edge without them, fail-closed, because an
    edge nobody can trace back to a resolver and a run is unreviewable.
    """
    return GraphEdge(source_id=src, target_id=dst, repo_id=repo, type=etype,
                     evidence=["f.py:1"], detected_by="resolver.test@1",
                     created_by="linker", link_run_id="linkrun_test")


def _scratch_neo4j():
    """A disposable Neo4j, never the deployment's own.

    `ADDUCE_SCRATCH_NEO4J_URI` must point at a throwaway instance: this
    fixture writes and deletes nodes, and running it against a real estate
    would leave `CALLS_SERVICE` edges behind — the exact relationship the
    accuracy harness counts.

        docker run --rm -d --name adduce-scratch-neo4j -p 27699:7687 \
          -e NEO4J_AUTH=neo4j/scratchpassword123 neo4j:5.26-community
        export ADDUCE_SCRATCH_NEO4J_URI=bolt://localhost:27699
        export ADDUCE_SCRATCH_NEO4J_PASSWORD=scratchpassword123
    """
    uri = os.environ.get("ADDUCE_SCRATCH_NEO4J_URI")
    if not uri:
        pytest.skip("no scratch Neo4j; see _scratch_neo4j for how to start one")

    from adduce.db import neo4j_client, store_config
    from adduce.db.neo4j_graph_store import Neo4jGraphStore

    store_config.configure(
        neo4j_uri=uri, neo4j_user="neo4j",
        neo4j_password=os.environ.get("ADDUCE_SCRATCH_NEO4J_PASSWORD", ""))
    neo4j_client._driver = None          # rebind to the scratch instance
    with neo4j_client.get_session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
    return Neo4jGraphStore()


# A5's exit criterion, as a fixture: the same suite, every backend. A
# behaviour that holds in memory but not in SQLite is a portability bug, and
# running them separately is how that stays undiscovered.
@pytest.fixture(params=["memory", "sqlite", "neo4j"])
def store(request):
    if request.param == "memory":
        s = InMemoryGraphStore()
    elif request.param == "sqlite":
        s = SQLiteGraphStore(":memory:")
    else:
        s = _scratch_neo4j()
    s.upsert_nodes([node("a"), node("b"), node("c"), node("d")])
    s.upsert_edges([edge("a", "b"), edge("b", "c"), edge("c", "d"),
                    edge("a", "d", etype="ROUTES_TO")])
    return s


def count(store, subject, **filters):
    """Ask through the protocol, never a backend's internals — a test that
    reads `store.edges` only works on the backend that happens to keep a
    Python list, which is how a portable suite stops being portable."""
    return store.query(Aggregate(subject, filters=filters)).rows[0]["count"]


class TestUpsert:
    def test_nodes_are_replaced_not_duplicated(self, store):
        """Upserting a node twice updates it; it does not add a second one.

        Re-typing is deliberately not exercised: Neo4j MERGEs per label, so
        changing a node's type yields a second node under the new label
        rather than replacing the first — and deleting the old one would
        detach its edges. Node identity is (id, type), not id alone, and a
        backend cannot paper over that without losing relationships.
        """
        again = node("a")
        again.name = "renamed"
        store.upsert_nodes([again])
        assert count(store, "node") == 4

    def test_edges_dedupe_on_source_type_target(self, store):
        before = count(store, "edge")
        store.upsert_edges([edge("a", "b")])
        assert count(store, "edge") == before

    def test_same_pair_different_type_is_a_distinct_edge(self, store):
        before = count(store, "edge")
        store.upsert_edges([edge("a", "b", etype="DEPENDS_ON")])
        assert count(store, "edge") == before + 1


class TestNeighbourhood:
    def test_one_hop_out(self, store):
        rows = store.query(Neighbourhood("a", direction="out")).rows
        assert sorted(r["node_id"] for r in rows) == ["b", "d"]

    def test_hops_expand_transitively(self, store):
        rows = store.query(
            Neighbourhood("a", edge_types=("CALLS_SERVICE",), hops=3,
                          direction="out")).rows
        assert sorted(r["node_id"] for r in rows) == ["b", "c", "d"]
        assert {r["node_id"]: r["hops"] for r in rows}["c"] == 2

    def test_edge_type_filter_excludes_others(self, store):
        rows = store.query(
            Neighbourhood("a", edge_types=("ROUTES_TO",), direction="out")).rows
        assert [r["node_id"] for r in rows] == ["d"]

    def test_direction_in(self, store):
        rows = store.query(Neighbourhood("d", direction="in")).rows
        assert sorted(r["node_id"] for r in rows) == ["a", "c"]

    def test_limit_marks_truncated(self, store):
        result = store.query(Neighbourhood("a", hops=3, limit=1))
        assert len(result.rows) == 1
        assert result.truncated is True

    def test_unknown_node_returns_nothing(self, store):
        assert store.query(Neighbourhood("nope")).rows == []


class TestBoundedPath:
    def test_finds_both_routes(self, store):
        rows = store.query(BoundedPath("a", "d")).rows
        assert [r["hops"] for r in rows] == [1, 3]

    def test_max_hops_excludes_the_long_one(self, store):
        rows = store.query(
            BoundedPath("a", "d", edge_types=("CALLS_SERVICE",),
                        max_hops=2)).rows
        assert rows == []

    def test_cycles_do_not_hang(self, store):
        store.upsert_edges([edge("d", "a")])
        rows = store.query(BoundedPath("a", "d", max_hops=8)).rows
        assert rows, "a cycle must not swallow every path"


class TestAggregate:
    def test_counts_all_edges(self, store):
        assert store.query(Aggregate("edge")).rows == [{"count": 4}]

    def test_group_by_type(self, store):
        rows = store.query(Aggregate("edge", group_by=("type",))).rows
        assert {r["type"]: r["count"] for r in rows} == {
            "CALLS_SERVICE": 3, "ROUTES_TO": 1}

    def test_filters_apply(self, store):
        rows = store.query(
            Aggregate("edge", filters={"type": "ROUTES_TO"})).rows
        assert rows == [{"count": 1}]


class TestDeleteByRun:
    def test_removes_only_that_run(self, store):
        keep, drop = edge("a", "c"), edge("b", "d")
        keep.link_run_id, drop.link_run_id = "run1", "run2"
        store.upsert_edges([keep, drop])
        store.delete_by_run("run2")
        assert count(store, "edge", link_run_id="run2") == 0
        assert count(store, "edge", link_run_id="run1") == 1


class TestUnsupportedSpec:
    def test_rejects_an_unknown_spec_rather_than_guessing(self, store):
        with pytest.raises(TypeError, match="unsupported QuerySpec"):
            store.query("MATCH (n) RETURN n")


class TestLinkerStoreClaims:
    def test_claims_round_trip_from_scan_output(self):
        """A claim node plus its evidence edge must come back as the record
        the linker consumes — this is the same round trip Neo4j performs."""
        claim = GraphNode(
            id="claim1", repo_id="r1", type="ContractClaim", name="k",
            label="l", extra_props={"kind": "http", "direction": "consumes",
                                    "key": "GET /v1/x", "matchable": True,
                                    "hint_source": "compose",
                                    "evidence": ["a.py:3"],
                                    "service_hint": "billing"},
            metadata={"template": "/v1/x"})
        sink = type("Sink", (), {})()
        sink.nodes = [claim, node("file1", ntype="File")]
        sink.edges = [edge("claim1", "file1", etype="EVIDENCED_BY")]

        store = InMemoryLinkerStore([sink])
        claims = store.load_claims()
        assert len(claims) == 1
        got = claims[0]
        assert got.kind == "http" and got.key == "GET /v1/x"
        assert got.service_hint == "billing"
        assert got.attrs == {"template": "/v1/x"}
        assert got.evidence_node_id == "file1"
        assert got.evidence_node_type == "File"

    def test_claim_without_evidence_node_is_kept_not_dropped(self):
        """Dropping it here would be a decline no counter ever records."""
        claim = GraphNode(id="c2", repo_id="r1", type="ContractClaim",
                          name="k", label="l",
                          extra_props={"kind": "topic", "matchable": True})
        sink = type("Sink", (), {})()
        sink.nodes, sink.edges = [claim], []
        assert len(InMemoryLinkerStore([sink]).load_claims()) == 1


class TestDeterministicArtifact:
    """B6: same input twice produces identical bytes.

    Not tidiness — PR mode, caching, artifact diffing and CI gates are all
    unbuildable without it, because each one asks "did this change?" and gets
    a yes every time if the bytes move on their own.
    """

    def _snapshot(self, tmp_path, tag):
        import hashlib

        store = SQLiteGraphStore(str(tmp_path / f"{tag}.db"))
        store.upsert_nodes([node(x) for x in "abcdef"])
        store.upsert_edges([edge("a", "b"), edge("b", "c"),
                            edge("a", "d", etype="ROUTES_TO")])
        out = tmp_path / f"{tag}-snapshot.db"
        # VACUUM INTO writes a freshly packed file: no freelist, no leftover
        # page state from how the rows happened to arrive.
        store._conn.execute("VACUUM INTO ?", (str(out),))
        store.close()
        return hashlib.sha256(out.read_bytes()).hexdigest()

    def test_two_runs_produce_identical_bytes(self, tmp_path):
        assert self._snapshot(tmp_path, "one") == self._snapshot(tmp_path, "two")

    def test_wall_clock_fields_never_enter_the_artifact(self, tmp_path):
        """`GraphEdge.created_at` defaults to `datetime.now()`. Embedding it
        would make every artifact differ from every other one, so it is
        excluded from the content and kept as metadata."""
        import json

        from adduce.db.sqlite_store import _VOLATILE

        store = SQLiteGraphStore(":memory:")
        store.upsert_edges([edge("a", "b")])
        row = store._conn.execute("SELECT payload FROM edges").fetchone()
        payload = json.loads(row["payload"])
        assert not (set(payload) & set(_VOLATILE)), payload
