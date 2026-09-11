"""`GraphStore` over SQLite: the zero-infrastructure default.

A SQLite file *is* the portable artifact (architecture §5.3), so one decision
covers the default backend, the per-repo artifact format, and byte-level
determinism at once.

The traversal port is small because the codebase never uses `shortestPath` —
the one traversal with no recursive-CTE equivalent. What remains is bounded
expansion (`*1..n` with an edge-type predicate), and recursive CTEs do that
directly.

**Cycles.** `BoundedPath` carries the path it has walked and refuses to re-enter
a node. Without that a cyclic estate does not return a wrong answer, it never
returns at all — and real estates have cycles (two services calling each
other through a gateway is one).
"""

import json
import sqlite3
import threading

from evigraph.db.graph_store import Aggregate, BoundedPath, Neighbourhood, Result

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id        TEXT PRIMARY KEY,
    repo_id   TEXT,
    type      TEXT,
    name      TEXT,
    payload   TEXT
);
CREATE TABLE IF NOT EXISTS edges (
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    type        TEXT NOT NULL,
    repo_id     TEXT,
    confidence  REAL,
    status      TEXT,
    link_run_id TEXT,
    payload     TEXT,
    PRIMARY KEY (source_id, type, target_id)
);
CREATE INDEX IF NOT EXISTS edges_source ON edges (source_id, type);
CREATE INDEX IF NOT EXISTS edges_target ON edges (target_id, type);
CREATE INDEX IF NOT EXISTS nodes_type ON nodes (type);
"""


# Fields whose value is the moment the object was constructed, not anything
# about the graph. `GraphEdge.created_at` defaults to `datetime.now()`, so an
# artifact that embeds it differs on every run — the same inputs producing
# different bytes, which is exactly what B6 forbids and what PR-mode diffing,
# caching and CI gates are all built on top of.
#
# They are excluded from the artifact rather than from the model: when a row
# was first written is real operational metadata, it just is not a fact about
# the estate and must not enter the content.
_VOLATILE = ("created_at", "updated_at", "last_seen_at", "first_seen_at")


def _payload(obj) -> str:
    """Everything the columns do not hold, so nothing is lost on the way in.

    Sorted keys because this file is an artifact: two runs over the same
    inputs must produce the same bytes, and dict order would break that.
    """
    return json.dumps({k: v for k, v in vars(obj).items()
                       if k not in _VOLATILE},
                      default=str, sort_keys=True)


class SQLiteGraphStore:
    """Implements `GraphStore` on a SQLite file, or `:memory:` for tests."""

    def __init__(self, path: str = ":memory:"):
        # `check_same_thread=False` plus an explicit lock, rather than a
        # connection per thread: a link run has many writers and one file, and
        # SQLite serialises writes anyway. Without this, a threaded writer
        # raises ProgrammingError and its edges are lost outright — not
        # corrupted, simply absent, which is the silent kind of wrong.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- writes -----------------------------------------------------------

    def upsert_nodes(self, nodes) -> None:
        rows = [(n.id, getattr(n, "repo_id", None), getattr(n, "type", None),
                 getattr(n, "name", None), _payload(n)) for n in nodes]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO nodes (id, repo_id, type, name, payload) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "repo_id=excluded.repo_id, type=excluded.type, "
                "name=excluded.name, payload=excluded.payload", rows)
            self._conn.commit()

    def upsert_edges(self, edges) -> None:
        rows = [(e.source_id, e.target_id, e.type, getattr(e, "repo_id", None),
                 getattr(e, "confidence", None), getattr(e, "status", None),
                 getattr(e, "link_run_id", None), _payload(e)) for e in edges]
        with self._lock:
            self._conn.executemany(
                "INSERT INTO edges (source_id, target_id, type, repo_id, "
                "confidence, status, link_run_id, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id, type, target_id) DO UPDATE SET "
                "repo_id=excluded.repo_id, confidence=excluded.confidence, "
                "status=excluded.status, link_run_id=excluded.link_run_id, "
                "payload=excluded.payload", rows)
            self._conn.commit()

    def delete_by_run(self, link_run_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM edges WHERE link_run_id = ?",
                               (link_run_id,))
            self._conn.commit()

    # --- reads ------------------------------------------------------------

    def query(self, spec) -> Result:
        if isinstance(spec, Neighbourhood):
            return self._neighbourhood(spec)
        if isinstance(spec, BoundedPath):
            return self._paths(spec)
        if isinstance(spec, Aggregate):
            return self._aggregate(spec)
        raise TypeError(f"unsupported QuerySpec: {type(spec).__name__}")

    @staticmethod
    def _type_predicate(edge_types, alias="e") -> tuple[str, list]:
        """The predicate alone — the caller supplies WHERE or AND.

        Returning it pre-joined is how the first version emitted `AND` into a
        select that had no WHERE clause at all.
        """
        if not edge_types:
            return "", []
        marks = ",".join("?" * len(edge_types))
        return f"{alias}.type IN ({marks})", list(edge_types)

    @staticmethod
    def _step(direction: str) -> str:
        """The (from, to) column pair each hop follows."""
        if direction == "out":
            return "SELECT e.source_id AS frm, e.target_id AS too, e.type FROM edges e"
        if direction == "in":
            return "SELECT e.target_id AS frm, e.source_id AS too, e.type FROM edges e"
        return ("SELECT e.source_id AS frm, e.target_id AS too, e.type FROM edges e"
                " UNION ALL "
                "SELECT e.target_id AS frm, e.source_id AS too, e.type FROM edges e")

    def _neighbourhood(self, spec: Neighbourhood) -> Result:
        pred, params = self._type_predicate(spec.edge_types)
        where = f" WHERE {pred}" if pred else ""
        # `both` unions two selects, so the type predicate binds twice.
        step = self._step(spec.direction)
        if spec.direction == "both":
            first, second = step.split(" UNION ALL ")
            step = f"{first}{where} UNION ALL {second}{where}"
            step_params = params + params
        else:
            step = f"{step}{where}"
            step_params = list(params)

        sql = f"""
        WITH RECURSIVE steps AS ({step}),
        walk(node_id, depth, via) AS (
            SELECT too, 1, type FROM steps WHERE frm = ?
            UNION
            SELECT s.too, w.depth + 1, s.type
            FROM steps s JOIN walk w ON s.frm = w.node_id
            WHERE w.depth < ?
        )
        SELECT node_id, MIN(depth) AS hops,
               via FROM walk WHERE node_id <> ?
        GROUP BY node_id ORDER BY hops, node_id LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(
                sql, step_params + [spec.node_id, max(int(spec.hops), 0),
                                spec.node_id, spec.limit + 1]).fetchall()
        truncated = len(rows) > spec.limit
        return Result(
            rows=[{"node_id": r["node_id"], "hops": r["hops"],
                   "via": r["via"] or ""} for r in rows[:spec.limit]],
            truncated=truncated)

    def _paths(self, spec: BoundedPath) -> Result:
        pred, params = self._type_predicate(spec.edge_types)
        clause = f" AND {pred}" if pred else ""
        sql = f"""
        WITH RECURSIVE walk(node, path, hops) AS (
            SELECT ?, ',' || ? || ',', 0
            UNION ALL
            SELECT e.target_id, w.path || e.target_id || ',', w.hops + 1
            FROM edges e JOIN walk w ON e.source_id = w.node
            WHERE w.hops < ?{clause}
              AND instr(w.path, ',' || e.target_id || ',') = 0
        )
        SELECT path, hops FROM walk
        WHERE node = ? AND hops >= 1 ORDER BY hops, path LIMIT ?
        """
        with self._lock:
            rows = self._conn.execute(
                sql, [spec.source_id, spec.source_id, max(int(spec.max_hops), 0)]
            + params + [spec.target_id, spec.limit + 1]).fetchall()
        truncated = len(rows) > spec.limit
        return Result(
            rows=[{"path": [p for p in r["path"].split(",") if p],
                   "hops": r["hops"]} for r in rows[:spec.limit]],
            truncated=truncated)

    def _aggregate(self, spec: Aggregate) -> Result:
        table = "nodes" if spec.subject == "node" else "edges"
        filters = spec.filters or {}
        where = " AND ".join(f"{k} = ?" for k in filters)
        clause = f" WHERE {where}" if where else ""
        values = list(filters.values())

        if not spec.group_by:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS count FROM {table}{clause}",
                values).fetchone()
            return Result(rows=[{"count": row["count"]}])

        keys = ", ".join(spec.group_by)
        with self._lock:
            rows = self._conn.execute(
            f"SELECT {keys}, COUNT(*) AS count FROM {table}{clause} "
            f"GROUP BY {keys} ORDER BY {keys} LIMIT ?",
            values + [spec.limit + 1]).fetchall()
        truncated = len(rows) > spec.limit
        return Result(rows=[dict(r) for r in rows[:spec.limit]],
                      truncated=truncated)
