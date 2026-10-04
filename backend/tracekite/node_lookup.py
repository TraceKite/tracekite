"""Node identity lookup for graph-query surfaces.

The link result intentionally carries only services, rendezvous nodes and
edges.  Directory scans still have their Layer-0 nodes in memory, while
portable artifacts keep those nodes in SQLite.  This protocol lets MCP graph
queries resolve either source without making the pure query code know how the
nodes were stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


NodeRecord = dict[str, object]


class NodeLookup(Protocol):
    def get(self, node_id: str) -> NodeRecord | None: ...

    def search(self, query: str, limit: int) -> list[NodeRecord]: ...


def node_record(node) -> NodeRecord:
    """The stable, useful identity fields from a stored graph node."""
    record: NodeRecord = {
        "id": str(getattr(node, "id", "")),
        "type": str(getattr(node, "type", "")),
        "name": str(getattr(node, "name", "")),
        "label": str(getattr(node, "label", "") or getattr(node, "name", "")),
        "repo_id": str(getattr(node, "repo_id", "") or ""),
        "path": getattr(node, "path", None),
        "language": getattr(node, "language", None),
        "start_line": getattr(node, "start_line", None),
        "end_line": getattr(node, "end_line", None),
    }
    properties = dict(getattr(node, "extra_props", {}) or {})
    if properties:
        record["properties"] = properties
    return record


def search_rank(record: NodeRecord, query: str) -> tuple[int, int, str] | None:
    """Exact spelling, exact case-folded, prefix, name/label, path, then id."""
    raw = query.strip()
    folded = raw.casefold()
    node_id = str(record.get("id") or "")
    name = str(record.get("name") or "")
    label = str(record.get("label") or "")
    path = str(record.get("path") or "")
    values = (name, label, node_id)
    lowered = tuple(value.casefold() for value in values)
    if raw in values:
        tier = 0
    elif folded in lowered:
        tier = 1
    elif any(value.startswith(folded) for value in lowered):
        tier = 2
    elif any(folded in value for value in lowered[:2]):
        tier = 3
    elif folded in path.casefold():
        tier = 4
    elif folded in lowered[2]:
        tier = 5
    else:
        return None
    return tier, len(name or label or node_id), node_id


@dataclass
class InMemoryNodeLookup:
    records: dict[str, NodeRecord] = field(default_factory=dict)

    @classmethod
    def from_nodes(cls, nodes) -> "InMemoryNodeLookup":
        return cls({record["id"]: record for record in map(node_record, nodes)
                    if record["id"]})

    def get(self, node_id: str) -> NodeRecord | None:
        return self.records.get(node_id)

    def search(self, query: str, limit: int) -> list[NodeRecord]:
        ranked = [(rank, record) for record in self.records.values()
                  if record.get("type") != "ContractClaim"
                  if (rank := search_rank(record, query)) is not None]
        return [record for _, record in sorted(ranked, key=lambda item: item[0])[:limit]]


@dataclass
class CompositeNodeLookup:
    lookups: list[NodeLookup] = field(default_factory=list)

    def get(self, node_id: str) -> NodeRecord | None:
        for lookup in self.lookups:
            if record := lookup.get(node_id):
                return record
        return None

    def search(self, query: str, limit: int) -> list[NodeRecord]:
        by_id: dict[str, NodeRecord] = {}
        for lookup in self.lookups:
            for record in lookup.search(query, limit):
                by_id.setdefault(str(record["id"]), record)
        ranked = [(rank, record) for record in by_id.values()
                  if (rank := search_rank(record, query)) is not None]
        return [record for _, record in sorted(ranked, key=lambda item: item[0])
                ][:limit]


class EmptyNodeLookup:
    def get(self, node_id: str) -> NodeRecord | None:
        return None

    def search(self, query: str, limit: int) -> list[NodeRecord]:
        return []
