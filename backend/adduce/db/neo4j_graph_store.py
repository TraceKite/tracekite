"""`GraphStore` over Neo4j.

The opt-in backend, for teams already running a graph database. Writes
delegate to `graph_writer`, which owns batching, edge dedupe and the
missing-endpoint diagnostics — restating that Cypher here would be a second
implementation of the write path, drifting from the first.

Reads are the new part. Each `QuerySpec` becomes one parameterised Cypher
statement with its bound baked in, because the protocol's whole point is that
a caller describes a question and never hands a backend a query string.

`shortestPath` is deliberately not used anywhere here: it is the one traversal
with no recursive-CTE equivalent, so using it would make B2 unportable.

**Node patterns carry no label.** Ingestion nodes are `:GraphNode`, but the
Service and rendezvous nodes the linker mints are not — matching on the label
silently returns nothing for exactly the cross-repo nodes a caller most wants
to traverse. Matching on `id` alone is correct and is backed by an index.
"""

import logging
import re

from adduce.db.graph_store import Aggregate, BoundedPath, Neighbourhood, Result
from adduce.db.neo4j_client import get_session
from adduce.services import graph_writer

logger = logging.getLogger(__name__)

# A traversal without an edge-type predicate walks the whole graph. Every
# variable-length query in this codebase carries one; this keeps that true.
_ANY_EDGE = ""

# A Cypher relationship type: a bare identifier. Everything an edge type has
# ever been in this graph is SCREAMING_SNAKE_CASE, and nothing legitimate
# needs a space, quote, bracket or colon.
_EDGE_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _rel_pattern(edge_types) -> str:
    """`:A|B` for a relationship pattern, or nothing.

    Cypher cannot bind a relationship type as a parameter — it is syntax, not
    a value — so this is the one place a caller's string reaches a query
    uninterpolated, and the only defence is refusing anything that is not a
    bare type name. The SQLite store answers the same `QuerySpec` with `?`
    placeholders and is safe by construction; this one has to be made safe on
    purpose.

    Not reachable from a request today: `/api/repos/{id}/graph` passes its
    `edge_types` to `graph_reader`, which binds `$edge_types`. It becomes
    reachable the moment this store is wired up as the read path, and a
    validation gap is much cheaper to close before that than after.

    Fails closed on anything that is not an identifier, rather than checking
    against a list of known types: a type added tomorrow keeps working, and
    `DELETE` smuggled through a comma never does.
    """
    if not edge_types:
        return _ANY_EDGE
    for name in edge_types:
        if not _EDGE_TYPE.fullmatch(str(name)):
            raise ValueError(f"not a relationship type: {name!r}")
    return f":{'|'.join(edge_types)}"


def _arrows(direction: str) -> tuple[str, str]:
    if direction == "out":
        return "-", "->"
    if direction == "in":
        return "<-", "-"
    return "-", "-"


class Neo4jGraphStore:
    """Implements `GraphStore` against the application's Neo4j session."""

    # --- writes -----------------------------------------------------------

    def upsert_nodes(self, nodes) -> None:
        graph_writer.write_nodes_batch(list(nodes))

    def upsert_edges(self, edges) -> None:
        """Route each edge to the writer that owns its type.

        Ingestion edges (CONTAINS, DECLARES, …) and linker edges
        (CALLS_SERVICE, ROUTES_TO, …) have separate fail-closed allowlists,
        and each writer rejects the other's types outright. A single
        `GraphStore.upsert_edges` must therefore split them — passing
        everything to one writer is how this backend rejected exactly the
        cross-repo edges the protocol exists to store.
        """
        linker, ingestion = [], []
        for edge in edges:
            (linker if edge.type in graph_writer.LINKER_EDGE_TYPES
             else ingestion).append(edge)
        if ingestion:
            graph_writer.write_edges_batch(ingestion)
        if linker:
            graph_writer.write_linker_edges(linker)

    def delete_by_run(self, link_run_id: str) -> None:
        with get_session() as session:
            session.run(
                "MATCH ()-[r]->() WHERE r.link_run_id = $run "
                "CALL { WITH r DELETE r } IN TRANSACTIONS OF 5000 ROWS",
                run=link_run_id).consume()

    # --- reads ------------------------------------------------------------

    def query(self, spec) -> Result:
        if isinstance(spec, Neighbourhood):
            return self._neighbourhood(spec)
        if isinstance(spec, BoundedPath):
            return self._paths(spec)
        if isinstance(spec, Aggregate):
            return self._aggregate(spec)
        raise TypeError(f"unsupported QuerySpec: {type(spec).__name__}")

    def _neighbourhood(self, spec: Neighbourhood) -> Result:
        left, right = _arrows(spec.direction)
        rel = _rel_pattern(spec.edge_types)
        # hops is interpolated, not bound: Cypher does not accept a parameter
        # inside a variable-length bound. It is an int from a frozen dataclass,
        # and coerced again here so no caller can smuggle a string through.
        hops = max(int(spec.hops), 0)
        with get_session() as session:
            rows = session.run(
                f"MATCH (s {{id: $id}}) "
                f"MATCH path = (s){left}[r{rel}*1..{hops}]{right}(n) "
                f"RETURN DISTINCT n.id AS node_id, length(path) AS hops, "
                f"type(last(relationships(path))) AS via "
                f"ORDER BY hops, node_id LIMIT $limit",
                id=spec.node_id, limit=spec.limit + 1).data()
        truncated = len(rows) > spec.limit
        return Result(
            rows=[{"node_id": r["node_id"], "hops": r["hops"],
                   "via": r["via"] or ""}
                  for r in rows[:spec.limit]],
            truncated=truncated)

    def _paths(self, spec: BoundedPath) -> Result:
        rel = _rel_pattern(spec.edge_types)
        max_hops = max(int(spec.max_hops), 1)
        with get_session() as session:
            rows = session.run(
                f"MATCH (s {{id: $src}}), (t {{id: $dst}}) "
                f"MATCH path = (s)-[r{rel}*1..{max_hops}]->(t) "
                f"RETURN [n IN nodes(path) | n.id] AS path, "
                f"length(path) AS hops "
                f"ORDER BY hops LIMIT $limit",
                src=spec.source_id, dst=spec.target_id,
                limit=spec.limit + 1).data()
        truncated = len(rows) > spec.limit
        return Result(rows=[{"path": r["path"], "hops": r["hops"]}
                            for r in rows[:spec.limit]],
                      truncated=truncated)

    def _aggregate(self, spec: Aggregate) -> Result:
        subject = "(n)" if spec.subject == "node" else "()-[n]->()"

        def _ref(attr: str) -> str:
            """A relationship's type is `type(n)`, not a property. Filtering
            on `n.type` matches nothing and reports zero, which reads exactly
            like a correct empty answer."""
            if attr == "type" and spec.subject != "node":
                return "type(n)"
            return f"n.{attr}"

        where = " AND ".join(f"{_ref(k)} = ${k}" for k in (spec.filters or {}))
        clause = f"WHERE {where} " if where else ""
        with get_session() as session:
            if not spec.group_by:
                row = session.run(
                    f"MATCH {subject} {clause}RETURN count(n) AS count",
                    **(spec.filters or {})).single()
                return Result(rows=[{"count": (row or {}).get("count", 0)}])
            keys = ", ".join(f"{_ref(a)} AS {a}" for a in spec.group_by)
            rows = session.run(
                f"MATCH {subject} {clause}RETURN {keys}, count(*) AS count "
                f"ORDER BY {', '.join(spec.group_by)} LIMIT $limit",
                limit=spec.limit + 1, **(spec.filters or {})).data()
        return Result(rows=rows[:spec.limit], truncated=len(rows) > spec.limit)
