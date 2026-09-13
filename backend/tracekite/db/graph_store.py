"""The storage protocol every backend implements (architecture §5.1).

Four methods, and a `QuerySpec` that is a **typed description of a question,
not a query string**. That constraint is the whole design: a backend that only
speaks SQL must never have to parse Cypher, and today's four variable-length
traversals are all bounded with edge-type predicates, so recursive CTEs cover
them. `shortestPath` is deliberately never used — it is the one traversal that
is genuinely hard to port.

SQLiteGraphStore, Neo4jGraphStore and InMemoryGraphStore implement this protocol
in sibling modules. SQLite also serves the portable artifact format. Shared
conformance tests cover the backends; live Neo4j coverage requires its fixture.

`LinkerStore` in `services/linker/ports.py` remains the active narrower port
covering one link run; the existence of GraphStore does not retire that port.
"""

from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

from tracekite.models.graph_models import GraphEdge, GraphNode


@dataclass(frozen=True)
class Neighbourhood:
    """Nodes one to `hops` steps from `node_id`, following `edge_types`.

    Bounded on purpose: an unbounded expansion is the query that pins a
    database, and every traversal in this codebase already carries a limit.
    """

    node_id: str
    edge_types: Sequence[str] = ()
    hops: int = 1
    direction: str = "both"          # out | in | both
    limit: int = 1000


@dataclass(frozen=True)
class BoundedPath:
    """Paths from `source_id` to `target_id`, at most `max_hops` long.

    `max_hops` is capped by the caller and never optional — this is the shape
    `/api/v2/trace` needs, and the reason it is expressible in SQL at all.
    """

    source_id: str
    target_id: str
    edge_types: Sequence[str] = ()
    max_hops: int = 8
    limit: int = 100


@dataclass(frozen=True)
class Aggregate:
    """A count or grouping over nodes/edges matching simple predicates."""

    subject: str                      # "node" | "edge"
    group_by: Sequence[str] = ()
    filters: dict = field(default_factory=dict)
    limit: int = 1000


QuerySpec = Neighbourhood | BoundedPath | Aggregate


@dataclass
class Result:
    """Rows a backend returned. Plain values — no driver types escape a store.

    A `Result` that crossed a backend boundary carrying a session, a record
    object, or a lazily-evaluated cursor would couple every caller to that
    backend, which is exactly what this protocol exists to prevent.
    """

    rows: list[dict] = field(default_factory=list)
    truncated: bool = False


class GraphStore(Protocol):
    """Operations supported by the portable backends (architecture §5.1)."""

    def upsert_nodes(self, nodes: Iterable[GraphNode]) -> None: ...

    def upsert_edges(self, edges: Iterable[GraphEdge]) -> None: ...

    def query(self, spec: QuerySpec) -> Result: ...

    def delete_by_run(self, link_run_id: str) -> None: ...
