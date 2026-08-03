"""What changed between two artifacts.

A resolver change is hard to review by reading it: the diff says what the code
now does, not what the graph now says. This answers the second question —
which edges appeared, which vanished, and which changed confidence.

Only possible because artifacts are byte-reproducible. Without that, every
comparison would be noise: two runs of unchanged code would differ, and a real
change would be indistinguishable from a timestamp.

Compared with ATTACH and SQL rather than in Python, for the same reason
compaction is: at a thousand repositories the set difference is the work.
"""

import sqlite3
from dataclasses import dataclass, field

from adduce.db.sqlite_store import SQLiteGraphStore


@dataclass
class EdgeDelta:
    added: list[tuple] = field(default_factory=list)
    removed: list[tuple] = field(default_factory=list)
    reconfidenced: list[tuple] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.reconfidenced)


@dataclass
class ArtifactDiff:
    nodes_added: int = 0
    nodes_removed: int = 0
    edges: EdgeDelta = field(default_factory=EdgeDelta)
    by_type: dict = field(default_factory=dict)

    @property
    def has_breaking_changes(self) -> bool:
        """True when contract edges or nodes were removed."""
        return bool(self.edges.removed or self.nodes_removed)

    @property
    def breaking_edges(self) -> list[list]:
        """Edge removals that break existing consumer contracts."""
        return [list(t) for t in self.edges.removed]

    def summary(self) -> str:
        """One line a reviewer can read without opening anything.

        Names the direction of every change: "27 edges added" and "27 edges
        removed" are very different reviews, and a single net number hides
        which happened.
        """
        e = self.edges
        if not (e.changed or self.nodes_added or self.nodes_removed):
            return "no change to the graph"
        parts = []
        if e.added:
            parts.append(f"+{len(e.added)} edges")
        if e.removed:
            parts.append(f"-{len(e.removed)} edges (BREAKING)")
        if e.reconfidenced:
            parts.append(f"~{len(e.reconfidenced)} reconfidenced")
        if self.nodes_added:
            parts.append(f"+{self.nodes_added} nodes")
        if self.nodes_removed:
            parts.append(f"-{self.nodes_removed} nodes (BREAKING)")
        return ", ".join(parts)

    def as_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "has_breaking_changes": self.has_breaking_changes,
            "breaking_edges": self.breaking_edges,
            "nodes_added": self.nodes_added,
            "nodes_removed": self.nodes_removed,
            "edges_added": [list(t) for t in self.edges.added],
            "edges_removed": [list(t) for t in self.edges.removed],
            "edges_reconfidenced": [list(t) for t in self.edges.reconfidenced],
            "by_type": dict(sorted(self.by_type.items())),
        }


def diff_artifacts(before: str, after: str, *, limit: int = 200) -> ArtifactDiff:
    """Compare two artifacts. `before` is the baseline.

    `limit` bounds the listed examples, not the counts: a reviewer needs the
    true magnitude even when only the first few are shown, and a truncated
    count would understate a regression.
    """
    store = SQLiteGraphStore(after)
    conn = store._conn                                       # noqa: SLF001
    with store._lock:                                        # noqa: SLF001
        conn.execute("ATTACH DATABASE ? AS base", (before,))
        try:
            result = _compare(conn, limit)
        finally:
            conn.execute("DETACH DATABASE base")
    store.close()
    return result


def _compare(conn: sqlite3.Connection, limit: int) -> ArtifactDiff:
    added = conn.execute(
        "SELECT source_id, type, target_id FROM edges "
        "EXCEPT SELECT source_id, type, target_id FROM base.edges "
        "ORDER BY type, source_id, target_id").fetchall()
    removed = conn.execute(
        "SELECT source_id, type, target_id FROM base.edges "
        "EXCEPT SELECT source_id, type, target_id FROM edges "
        "ORDER BY type, source_id, target_id").fetchall()
    # Same edge, different score: a resolver retuning is invisible to a set
    # difference, and it is exactly what a confidence change looks like.
    moved = conn.execute(
        "SELECT n.source_id, n.type, n.target_id, o.confidence, n.confidence "
        "FROM edges n JOIN base.edges o "
        "ON n.source_id = o.source_id AND n.type = o.type "
        "AND n.target_id = o.target_id "
        "WHERE n.confidence IS NOT o.confidence "
        "ORDER BY n.type, n.source_id").fetchall()

    nodes_added = conn.execute(
        "SELECT COUNT(*) FROM (SELECT id FROM nodes "
        "EXCEPT SELECT id FROM base.nodes)").fetchone()[0]
    nodes_removed = conn.execute(
        "SELECT COUNT(*) FROM (SELECT id FROM base.nodes "
        "EXCEPT SELECT id FROM nodes)").fetchone()[0]

    by_type: dict[str, dict[str, int]] = {}
    for rows, key in ((added, "added"), (removed, "removed")):
        for row in rows:
            by_type.setdefault(row[1], {"added": 0, "removed": 0})[key] += 1

    return ArtifactDiff(
        nodes_added=nodes_added, nodes_removed=nodes_removed,
        edges=EdgeDelta(added=[tuple(r) for r in added[:limit]],
                        removed=[tuple(r) for r in removed[:limit]],
                        reconfidenced=[tuple(r) for r in moved[:limit]]),
        by_type=by_type)
