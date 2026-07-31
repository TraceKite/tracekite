"""Move an existing Neo4j estate to SQLite without re-ingesting.

AD2 makes SQLite the default. Anyone already running the Docker stack has a
graph that took real time to build — re-ingesting it to change backend would
mean re-cloning every repository and re-parsing every file, and would silently
produce a *different* graph if any extractor changed in between.

So this copies. Nodes and edges move as rows; nothing is re-derived, which is
what makes the result comparable to what was there before rather than merely
similar.

Streamed in batches because an estate does not fit in memory at a thousand
repositories, and the point of the exercise is to still work there.
"""

import logging

from adduce.db.neo4j_client import get_session
from adduce.db.sqlite_store import SQLiteGraphStore, _payload

logger = logging.getLogger(__name__)

BATCH = 5000


class _Row:
    """A node or edge shaped enough for the SQLite store to write it.

    Deliberately not the real GraphNode/GraphEdge: reconstructing those would
    re-run their constructors, and `created_at` defaults to now — which would
    stamp the migration time onto every row and destroy the determinism B6
    depends on.
    """

    def __init__(self, props: dict):
        self.__dict__.update(props)


def _node_rows(session, skip: int):
    return session.run(
        "MATCH (n) WHERE n.id IS NOT NULL RETURN properties(n) AS p "
        "ORDER BY n.id SKIP $skip LIMIT $limit",
        skip=skip, limit=BATCH).data()


def _edge_rows(session, skip: int):
    return session.run(
        "MATCH (a)-[r]->(b) WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
        "RETURN a.id AS source_id, b.id AS target_id, type(r) AS type, "
        "properties(r) AS p ORDER BY a.id, type(r), b.id "
        "SKIP $skip LIMIT $limit", skip=skip, limit=BATCH).data()


def migrate_to_sqlite(out_path: str) -> dict:
    """Copy the live Neo4j graph into a SQLite file. Returns what moved."""
    store = SQLiteGraphStore(out_path)
    nodes = edges = 0

    with get_session() as session:
        while True:
            rows = _node_rows(session, nodes)
            if not rows:
                break
            store.upsert_nodes([_Row(r["p"]) for r in rows])
            nodes += len(rows)
            logger.info("migrated %d nodes", nodes)

        while True:
            rows = _edge_rows(session, edges)
            if not rows:
                break
            store.upsert_edges([
                _Row({**r["p"], "source_id": r["source_id"],
                      "target_id": r["target_id"], "type": r["type"]})
                for r in rows])
            edges += len(rows)
            logger.info("migrated %d edges", edges)

    store.close()
    return {"path": out_path, "nodes": nodes, "edges": edges}
