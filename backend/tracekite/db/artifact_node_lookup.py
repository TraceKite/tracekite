"""Lazy node identity lookup across portable TraceKite artifacts."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass

from tracekite.node_lookup import (
    CompositeNodeLookup,
    EmptyNodeLookup,
    InMemoryNodeLookup,
    NodeRecord,
    search_rank,
)


def _record(row: sqlite3.Row) -> NodeRecord:
    payload = json.loads(row["payload"] or "{}")
    return {
        "id": row["id"],
        "type": row["type"] or payload.get("type", ""),
        "name": row["name"] or payload.get("name", ""),
        "label": payload.get("label") or row["name"] or "",
        "repo_id": row["repo_id"] or payload.get("repo_id", ""),
        "path": payload.get("path"),
        "language": payload.get("language"),
        "start_line": payload.get("start_line"),
        "end_line": payload.get("end_line"),
        **({"properties": payload.get("extra_props")}
           if payload.get("extra_props") else {}),
    }


@dataclass
class ArtifactNodeLookup:
    paths: list[str]

    def get(self, node_id: str) -> NodeRecord | None:
        for path in self.paths:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT id, repo_id, type, name, payload FROM nodes WHERE id = ?",
                    (node_id,)).fetchone()
            if row is not None:
                return _record(row)
        return None

    def search(self, query: str, limit: int) -> list[NodeRecord]:
        rows: list[NodeRecord] = []
        pattern = f"%{query.casefold()}%"
        for path in self.paths:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                conn.row_factory = sqlite3.Row
                found = conn.execute(
                    "SELECT id, repo_id, type, name, payload FROM nodes "
                    "WHERE type <> 'ContractClaim' AND (lower(id) LIKE ? "
                    "OR lower(coalesce(name, '')) LIKE ? "
                    "OR lower(json_extract(payload, '$.label')) LIKE ? "
                    "OR lower(json_extract(payload, '$.path')) LIKE ?) "
                    "LIMIT ?",
                    (pattern, pattern, pattern, pattern, limit)).fetchall()
            rows.extend(_record(row) for row in found)
        ranked = [(rank, row) for row in rows
                  if (rank := search_rank(row, query)) is not None]
        return [row for _, row in sorted(ranked, key=lambda item: item[0])[:limit]]


def node_lookup_for_inputs(paths: list[str], sinks: dict) -> object:
    """Compose already-loaded scan nodes with lazy artifact lookups."""
    lookups = []
    nodes = [node for sink in sinks.values() for node in sink.nodes]
    if nodes:
        lookups.append(InMemoryNodeLookup.from_nodes(nodes))
    artifacts = [path for path in paths
                 if os.path.isfile(path) and path.endswith(".tracekite")]
    if artifacts:
        lookups.append(ArtifactNodeLookup(artifacts))
    if not lookups:
        return EmptyNodeLookup()
    if len(lookups) == 1:
        return lookups[0]
    return CompositeNodeLookup(lookups)
