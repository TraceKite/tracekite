"""`Neo4jGraphStore` against a real database.

Integration tier. These matter more than the in-memory equivalents: the
in-memory backend cannot disagree with itself, but Cypher can be accepted by
the driver and still answer the wrong question. Every bug found writing this
class was invisible to a mocked session — a label that silently matched
nothing, and a relationship the driver returns as a tuple.

The same behaviours `test_memory_store.py` pins, asked of Neo4j.
"""

import pytest

from tests.conftest import neo4j_available

from evigraph.db.graph_store import Aggregate, BoundedPath, Neighbourhood
from evigraph.db.neo4j_graph_store import Neo4jGraphStore

pytestmark = pytest.mark.skipif(not neo4j_available(),
                                reason="needs a running Neo4j")


@pytest.fixture(scope="module")
def store():
    return Neo4jGraphStore()


@pytest.fixture(scope="module")
def a_service_edge():
    """A real Service→Service edge, or skip: asserting against an empty graph
    would pass while proving nothing."""
    from evigraph.db.neo4j_client import get_session

    with get_session() as session:
        row = session.run(
            "MATCH (a:Service)-[:CALLS_SERVICE]->(b:Service) "
            "RETURN a.id AS a, b.id AS b LIMIT 1").single()
    if row is None:
        pytest.skip("no linked estate in the graph; ingest and link first")
    return row["a"], row["b"]


class TestQueriesAgainstRealData:
    def test_neighbourhood_traverses_linker_minted_nodes(self, store,
                                                         a_service_edge):
        """Service nodes carry no `:GraphNode` label. A pattern that requires
        one returns nothing for exactly the cross-repo nodes worth walking."""
        source, _ = a_service_edge
        result = store.query(Neighbourhood(
            source, edge_types=("CALLS_SERVICE",), hops=2, direction="out"))
        assert result.rows, "a known caller must have neighbours"
        assert all(r["via"] == "CALLS_SERVICE" for r in result.rows)
        assert all(1 <= r["hops"] <= 2 for r in result.rows)

    def test_bounded_path_respects_max_hops(self, store, a_service_edge):
        source, target = a_service_edge
        result = store.query(BoundedPath(
            source, target, edge_types=("CALLS_SERVICE",), max_hops=3))
        assert result.rows
        assert all(r["hops"] <= 3 for r in result.rows)
        assert all(r["path"][0] == source and r["path"][-1] == target
                   for r in result.rows)

    def test_limit_reports_truncation(self, store, a_service_edge):
        source, _ = a_service_edge
        result = store.query(Neighbourhood(
            source, edge_types=("CALLS_SERVICE",), hops=3, direction="out",
            limit=1))
        assert len(result.rows) == 1
        assert result.truncated is True, (
            "a caller that cannot tell it got a partial answer will treat it "
            "as the whole one")

    def test_aggregate_groups_by_edge_type(self, store):
        rows = store.query(Aggregate("edge", group_by=("type",))).rows
        by_type = {r["type"]: r["count"] for r in rows}
        assert by_type.get("CALLS_SERVICE", 0) > 0, by_type

    def test_rejects_a_query_string(self, store):
        """The protocol exists so a backend never parses someone's Cypher."""
        with pytest.raises(TypeError, match="unsupported QuerySpec"):
            store.query("MATCH (n) RETURN n")


class TestMigration:
    """An existing estate moves to SQLite without re-ingesting."""

    def test_the_graph_survives_the_backend_change(self, tmp_path):
        """Row counts are not the test — the answer is. If the service
        connections differ, something was lost, and copying rather than
        re-deriving exists precisely so they do not."""
        from evigraph.db.graph_store import Aggregate
        from evigraph.db.migrate import migrate_to_sqlite
        from evigraph.db.neo4j_client import get_session
        from evigraph.db.sqlite_store import SQLiteGraphStore

        out = str(tmp_path / "estate.db")
        result = migrate_to_sqlite(out)
        assert result["nodes"] > 0 and result["edges"] > 0

        with get_session() as session:
            before = session.run(
                "MATCH (:Service)-[r:CALLS_SERVICE]->(:Service) "
                "RETURN count(r) AS c").single()["c"]

        store = SQLiteGraphStore(out)
        after = {r["type"]: r["count"] for r in store.query(
            Aggregate("edge", group_by=("type",), limit=60)).rows}
        store.close()
        assert after.get("CALLS_SERVICE", 0) == before, (before, after)

    def test_migration_does_not_stamp_its_own_timestamp(self, tmp_path):
        """Reconstructing GraphEdge would set created_at to now, stamping
        the migration time onto every row and destroying determinism."""
        import json

        from evigraph.db.migrate import migrate_to_sqlite
        from evigraph.db.sqlite_store import SQLiteGraphStore

        out = str(tmp_path / "estate.db")
        migrate_to_sqlite(out)
        store = SQLiteGraphStore(out)
        row = store._conn.execute(
            "SELECT payload FROM edges LIMIT 1").fetchone()
        store.close()
        assert "created_at" not in json.loads(row["payload"])
