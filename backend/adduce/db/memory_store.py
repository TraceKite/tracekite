"""A `LinkerStore` held entirely in memory.

The zero-infrastructure backend: a host that has scanned some repositories can
link them without a database, a server, or a file on disk. It is also the
honest test of the store port — if a link run works against this, nothing in
the linker is secretly reaching for Neo4j.

Claims are reconstructed from scan output rather than re-derived. `scan()`
already emitted them as `ContractClaim` nodes with their evidence edge; this
reads those back into the `ClaimRecord` shape the linker consumes, which is
the same round trip Neo4j performs, minus the database.
"""

import hashlib

from adduce.db.graph_store import (
    Aggregate, BoundedPath, Neighbourhood, Result,
)
from adduce.services.linker.base import ClaimRecord

CLAIM_TYPE = "ContractClaim"
EVIDENCE_EDGE = "EVIDENCED_BY"


def claim_record(node_id: str, repo_id: str, props: dict, attrs: dict,
                 evidence_node: str | None,
                 evidence_node_type: str) -> ClaimRecord:
    """One claim node's fields, in the shape the linker consumes.

    Shared by every reader of persisted claims — the in-memory round trip
    here and the artifact reader — because the field mapping is a decision,
    and two copies of a decision drift.
    """
    return ClaimRecord(
        id=node_id,
        repo_id=repo_id or "",
        kind=props.get("kind", ""),
        direction=props.get("direction", ""),
        key=props.get("key", ""),
        service_hint=props.get("service_hint") or None,
        hint_source=props.get("hint_source", "none"),
        matchable=bool(props.get("matchable", False)),
        evidence=list(props.get("evidence") or []),
        attrs=dict(attrs or {}),
        evidence_node_id=evidence_node,
        evidence_node_type=evidence_node_type or "",
    )


def claims_from_scan(sink) -> list[ClaimRecord]:
    """Turn one scan's nodes and edges back into claim records.

    A claim whose evidence node is missing still counts: the linker decides
    what it can do without one, and dropping it here would be a silent
    decline that no counter ever records.
    """
    node_types = {n.id: n.type for n in sink.nodes}
    evidence_of = {e.source_id: e.target_id for e in sink.edges
                   if e.type == EVIDENCE_EDGE}

    records = []
    for node in sink.nodes:
        if node.type != CLAIM_TYPE:
            continue
        evidence_node = evidence_of.get(node.id)
        records.append(claim_record(
            node.id, node.repo_id, node.extra_props or {},
            node.metadata or {}, evidence_node,
            node_types.get(evidence_node, "") or ""))
    return records


class InMemoryLinkerStore:
    """Implements `LinkerStore` over scan output. No I/O of any kind."""

    def __init__(self, sinks=()):
        self._claims: list[ClaimRecord] = []
        self._stored_fingerprints: dict[str, str] = {}
        # What a link run produced, kept so a caller can read it back.
        self.edges: list = []
        self.rendezvous: list = []
        self.services: list = []
        self.link_runs: list[dict] = []
        self.linked_repos: list[tuple] = []
        for sink in sinks:
            self.add_scan(sink)

    def add_scan(self, sink) -> int:
        """Add one scanned repository's claims. Returns how many were added."""
        found = claims_from_scan(sink)
        self._claims.extend(found)
        return len(found)

    # --- reads ------------------------------------------------------------

    def load_claims(self) -> list[ClaimRecord]:
        return list(self._claims)

    def unlinkable_repos(self) -> dict[str, str]:
        # Claims arrive here already scanned; nothing is filtered by lifecycle.
        return {}

    def claim_fingerprints(self) -> dict[str, str]:
        by_repo: dict[str, list[str]] = {}
        for claim in self._claims:
            by_repo.setdefault(claim.repo_id, []).append(claim.id)
        return {repo: hashlib.sha256("\n".join(sorted(ids)).encode())
                .hexdigest()[:16] for repo, ids in by_repo.items()}

    def stored_fingerprints(self) -> dict[str, str]:
        return dict(self._stored_fingerprints)

    # --- writes -----------------------------------------------------------

    def store_fingerprints(self, fingerprints: dict[str, str]) -> None:
        self._stored_fingerprints.update(fingerprints)

    def create_link_run(self, run_id: str, mode: str) -> None:
        self.link_runs.append({"id": run_id, "mode": mode, "status": "running"})

    def finish_link_run(self, run_id: str, status: str, counters: dict,
                        error: str | None = None) -> None:
        for run in self.link_runs:
            if run["id"] == run_id:
                run.update(status=status, counters=counters, error=error)

    def write_rendezvous_nodes(self, specs: list) -> int:
        self.rendezvous = list(specs)
        return len(specs)

    def write_service_nodes(self, specs: list) -> int:
        self.services = list(specs)
        return len(specs)

    def write_linker_edges(self, edges: list) -> dict[str, int]:
        self.edges = list(edges)
        by_type: dict[str, int] = {}
        for edge in edges:
            by_type[edge.type] = by_type.get(edge.type, 0) + 1
        return by_type

    def delete_stale_linker_edges(self, current_run_id: str) -> int:
        # Nothing survives between runs in memory, so nothing is ever stale.
        return 0

    def stamp_repos_linked(self, repo_ids: list[str], run_id: str) -> None:
        self.linked_repos.append((tuple(repo_ids), run_id))

    def gc_orphan_rendezvous(self) -> int:
        return 0


class InMemoryGraphStore:
    """`GraphStore` (architecture §5.1) with no external service.

    Traversals are bounded here for the same reason they are bounded in the
    protocol: an unbounded expansion is the query that pins a database, and a
    backend that quietly allows one lets a caller write something no other
    backend can serve.
    """

    def __init__(self):
        self.nodes: dict[str, object] = {}
        self.edges: list = []

    # --- writes -----------------------------------------------------------

    def upsert_nodes(self, nodes) -> None:
        for node in nodes:
            self.nodes[node.id] = node

    def upsert_edges(self, edges) -> None:
        seen = {(e.source_id, e.type, e.target_id): i
                for i, e in enumerate(self.edges)}
        for edge in edges:
            key = (edge.source_id, edge.type, edge.target_id)
            if key in seen:
                self.edges[seen[key]] = edge
            else:
                seen[key] = len(self.edges)
                self.edges.append(edge)

    def delete_by_run(self, link_run_id: str) -> None:
        self.edges = [e for e in self.edges
                      if getattr(e, "link_run_id", None) != link_run_id]

    # --- reads ------------------------------------------------------------

    def query(self, spec) -> "Result":
        if isinstance(spec, Neighbourhood):
            return self._neighbourhood(spec)
        if isinstance(spec, BoundedPath):
            return self._paths(spec)
        if isinstance(spec, Aggregate):
            return self._aggregate(spec)
        raise TypeError(f"unsupported QuerySpec: {type(spec).__name__}")

    def _adjacent(self, node_id: str, edge_types, direction):
        for edge in self.edges:
            if edge_types and edge.type not in edge_types:
                continue
            if direction in ("out", "both") and edge.source_id == node_id:
                yield edge.target_id, edge
            if direction in ("in", "both") and edge.target_id == node_id:
                yield edge.source_id, edge

    def _neighbourhood(self, spec: "Neighbourhood") -> "Result":
        seen = {spec.node_id}
        frontier = [spec.node_id]
        rows: list[dict] = []
        for depth in range(1, max(spec.hops, 0) + 1):
            nxt = []
            for current in frontier:
                for neighbour, edge in self._adjacent(
                        current, spec.edge_types, spec.direction):
                    if neighbour in seen:
                        continue
                    seen.add(neighbour)
                    nxt.append(neighbour)
                    rows.append({"node_id": neighbour, "hops": depth,
                                 "via": edge.type})
                    if len(rows) >= spec.limit:
                        return Result(rows=rows, truncated=True)
            frontier = nxt
            if not frontier:
                break
        return Result(rows=rows)

    def _paths(self, spec: "BoundedPath") -> "Result":
        rows: list[dict] = []
        stack = [(spec.source_id, [spec.source_id])]
        while stack:
            current, path = stack.pop()
            if len(path) > spec.max_hops + 1:
                continue
            for neighbour, _edge in self._adjacent(
                    current, spec.edge_types, "out"):
                if neighbour in path:          # no cycles
                    continue
                if neighbour == spec.target_id:
                    # The bound applies to the completed path, not just to
                    # what we are willing to expand: accepting a hit one hop
                    # past max_hops returns a path no bounded backend would.
                    if len(path) <= spec.max_hops:
                        rows.append({"path": path + [neighbour],
                                     "hops": len(path)})
                        if len(rows) >= spec.limit:
                            return Result(rows=rows, truncated=True)
                elif len(path) <= spec.max_hops:
                    stack.append((neighbour, path + [neighbour]))
        return Result(rows=sorted(rows, key=lambda r: (r["hops"],
                                                       r["path"])))

    def _aggregate(self, spec: "Aggregate") -> "Result":
        items = (list(self.nodes.values()) if spec.subject == "node"
                 else list(self.edges))
        for attr, want in (spec.filters or {}).items():
            items = [i for i in items if getattr(i, attr, None) == want]
        if not spec.group_by:
            return Result(rows=[{"count": len(items)}])
        counts: dict[tuple, int] = {}
        for item in items:
            key = tuple(getattr(item, attr, None) for attr in spec.group_by)
            counts[key] = counts.get(key, 0) + 1
        rows = [dict(zip(spec.group_by, key), count=n)
                for key, n in sorted(counts.items(), key=lambda kv: str(kv[0]))]
        return Result(rows=rows[:spec.limit],
                      truncated=len(rows) > spec.limit)
