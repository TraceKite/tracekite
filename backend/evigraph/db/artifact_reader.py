"""Read an artifact back into something the engine can link.

`write_artifact` had no counterpart. Compaction merges artifacts in SQL and
diffing compares them in SQL, so nothing had needed to turn one back into
claims — but the temporal work does: "the graph at commit X" is a link run
over the artifacts at X (architecture §3.4), and that means loading them.

Nodes and edges come back as plain namespaces rather than `GraphNode` and
`GraphEdge`. The artifact's `payload` column is `vars(obj)` minus the volatile
timestamps, so reconstructing the model classes would mean guessing which of
their constructor arguments are required and inventing defaults for the
timestamps that were deliberately excluded. A namespace carries exactly what
was stored and nothing that was not — and `claims_from_scan` reads attributes,
not types.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from types import SimpleNamespace


@dataclass
class ArtifactContents:
    """One artifact's graph, shaped like the scan sink that produced it."""

    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    @property
    def head_sha(self) -> str:
        """The commit this artifact was scanned at, or "" if unrecorded.

        Empty rather than a guess: an artifact scanned before the sha was
        plumbed through has no commit, and inventing one would anchor a
        temporal answer to a commit that never existed.
        """
        return self.meta.get("head_sha", "")


def _row_to_object(row: sqlite3.Row, columns: dict) -> SimpleNamespace:
    """Payload first, then the indexed columns, which are authoritative."""
    payload = json.loads(row["payload"] or "{}")
    payload.update(columns)
    return SimpleNamespace(**payload)


def read_claims(path: str) -> list:
    """The artifact's claims, without materialising its graph.

    An artifact holds every node a scan produced; the link needs only the
    claims, which the 1,001-repo measurement put at ~2% of the rows — the
    other 98% cost 2.9 of a 5.8-second repush and were thrown away unread.
    Selecting claims in SQL keeps the estate's link-side memory O(claims)
    rather than O(nodes), which is what lets peak memory stay flat as the
    estate grows.

    Same field mapping as the in-memory round trip (`claim_record`), so the
    two readers cannot drift.
    """
    from evigraph.db.memory_store import CLAIM_TYPE, EVIDENCE_EDGE, claim_record

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT c.id, c.repo_id, c.payload, e.target_id AS enode, "
            "       n.type AS etype "
            "FROM nodes c "
            "LEFT JOIN edges e ON e.source_id = c.id AND e.type = ? "
            "LEFT JOIN nodes n ON n.id = e.target_id "
            "WHERE c.type = ? ORDER BY c.id, e.target_id",
            (EVIDENCE_EDGE, CLAIM_TYPE)).fetchall()
    finally:
        conn.close()

    # One record per claim, whichever evidence edge sorts last. Scans emit
    # exactly one per claim today; if one ever carries two, the join must
    # not silently double the claim, and "last by target id" is at least
    # the same answer on every run.
    by_id: dict[str, object] = {}
    for row in rows:
        payload = json.loads(row["payload"] or "{}")
        by_id[row["id"]] = claim_record(
            row["id"], row["repo_id"], payload.get("extra_props") or {},
            payload.get("metadata") or {}, row["enode"], row["etype"] or "")
    return list(by_id.values())


def read_artifact(path: str) -> ArtifactContents:
    """Every node and edge in one artifact, plus its metadata.

    Opened read-only: reading an artifact must never be able to change its
    digest, and a content-addressed file whose content moved is no longer the
    file its name claims.
    """
    from evigraph.db.artifact import read_meta

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        nodes = [
            _row_to_object(row, {"id": row["id"], "repo_id": row["repo_id"],
                                 "type": row["type"], "name": row["name"]})
            for row in conn.execute(
                "SELECT id, repo_id, type, name, payload FROM nodes "
                "ORDER BY id")
        ]
        edges = [
            _row_to_object(row, {
                "source_id": row["source_id"], "target_id": row["target_id"],
                "type": row["type"], "repo_id": row["repo_id"],
                "confidence": row["confidence"], "status": row["status"],
                "link_run_id": row["link_run_id"]})
            for row in conn.execute(
                "SELECT source_id, target_id, type, repo_id, confidence, "
                "status, link_run_id, payload FROM edges "
                "ORDER BY source_id, type, target_id")
        ]
    finally:
        conn.close()
    return ArtifactContents(nodes=nodes, edges=edges, meta=read_meta(path))
