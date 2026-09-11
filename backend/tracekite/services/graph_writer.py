"""Typed, reconciled write paths for graph data (design §5, Invariants 1/2/11).

Every edge is written under its concrete relationship type from an allowlisted
registry; writes count their results and raise on mismatch instead of
silently dropping rows.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tracekite.db.store_config import get_config
from tracekite.db.neo4j_client import get_session
from tracekite.models.graph_models import GraphEdge, GraphNode, REPO_STATES

logger = logging.getLogger(__name__)

# Layer-0 node types (design §2.2; Test/ExternalApi/ExternalSystem/Import are cut from v1).
NODE_LABELS = {
    "Repo": "Repo",
    "Folder": "Folder",
    "File": "File",
    "Class": "Class",
    "Interface": "Interface",
    "Method": "Method",
    "Function": "Function",
    "ApiEndpoint": "ApiEndpoint",
    "Dependency": "Dependency",
    "Config": "Config",
    "DockerResource": "DockerResource",
    "KubernetesResource": "KubernetesResource",
    "IaCResource": "IaCResource",
    "ContractClaim": "ContractClaim",
}

INGESTION_EDGE_TYPES = frozenset({
    "CONTAINS", "DECLARES", "CALLS", "EXPOSES_API", "DEPENDS_ON", "EVIDENCED_BY",
})

# Every type here must actually be emitted by a resolver. DEFINES_CONFIG,
# READS_CONFIG, SPEAKS_HTTP_TO and DEPLOYED_FROM were declared but never
# written by anything — the same schema fiction the claim-kind admission rule
# forbids, and it invites a UI to build a view for edges that cannot exist.
# Config ownership (VQ4) is answered from ContractClaim nodes directly.
LINKER_EDGE_TYPES = frozenset({
    "PUBLISHES", "DEPENDS_ON", "PUBLISHES_TO", "CONSUMES_FROM", "EXPOSES",
    "INVOKES", "UI_CALLS", "REGISTERS_WEBHOOK", "PERMITS_TRAFFIC",
    "HAS_ALIAS",
    "DECLARES_CONTRACT",
    "OWNED_BY", "RESOLVED_TO", "CALLS_SERVICE", "ROUTES_TO", "DEPENDS_ON_REPO",
    "MEMBER_OF", "BUILT_FROM", "BELONGS_TO", "DEPLOYED_AS",
    "DECLARES_TOPIC", "FANS_OUT_TO", "READS_FROM", "WRITES_TO",
    "SAME_OPERATION",
})

# ConfigKey likewise: constrained and indexed, but no resolver ever minted one.
RENDEZVOUS_LABELS = ("Library", "Topic", "ContractOperation", "HttpContract",
                     "ServiceName", "Team", "Dataset", "Module",
                     "DeploymentUnit")


class WriteReconciliationError(RuntimeError):
    """A write produced fewer relationships than rows submitted (Invariant 11)."""

    def __init__(self, edge_type: str, expected: int, written: int, samples: list[dict]):
        self.edge_type = edge_type
        self.expected = expected
        self.written = written
        self.samples = samples
        super().__init__(
            f"{edge_type}: expected {expected} edges, wrote {written}; "
            f"missing endpoints (sample): {samples[:5]}"
        )


@dataclass
class WriteReport:
    nodes_written: int = 0
    edges_by_type: dict = field(default_factory=dict)

    @property
    def edges_written(self) -> int:
        return sum(self.edges_by_type.values())


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _batches(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def write_nodes_batch(nodes: list[GraphNode]) -> int:
    """MERGE nodes per label; rejects node types outside the registry."""
    by_label: dict[str, list[dict]] = {}
    for node in nodes:
        label = NODE_LABELS.get(node.type)
        if label is None:
            raise ValueError(f"Node type {node.type!r} is not in the schema registry")
        by_label.setdefault(label, []).append(node.to_neo4j_props())

    total = 0
    with get_session() as session:
        for label, rows in by_label.items():
            for batch in _batches(rows, get_config().write_batch_size):
                result = session.run(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:GraphNode:{label} {{id: row.id}}) "
                    f"SET n += row "
                    f"RETURN count(n) AS c",
                    rows=batch,
                )
                total += result.single()["c"]
    return total


def _dedupe_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    """Collapse duplicate (source, type, target) rows, merging evidence and weight."""
    seen: dict[tuple, GraphEdge] = {}
    for edge in edges:
        key = (edge.source_id, edge.type, edge.target_id)
        if key in seen:
            kept = seen[key]
            kept.weight += 1
            merged = list(dict.fromkeys(kept.evidence + edge.evidence))
            kept.evidence = merged[:5]
        else:
            seen[key] = edge
    return list(seen.values())


def _diagnose_missing(session, rows: list[dict]) -> list[dict]:
    result = session.run(
        "UNWIND $rows AS row "
        "OPTIONAL MATCH (a:GraphNode {id: row.source}) "
        "OPTIONAL MATCH (b:GraphNode {id: row.target}) "
        "WITH row, a, b WHERE a IS NULL OR b IS NULL "
        "RETURN row.source AS source, row.target AS target, "
        "a IS NULL AS missing_source, b IS NULL AS missing_target LIMIT 10",
        rows=rows,
    )
    return [dict(record) for record in result]


def write_edges_batch(edges: list[GraphEdge]) -> dict[str, int]:
    """Write ingestion edges under concrete types with hard reconciliation."""
    for edge in edges:
        if edge.type not in INGESTION_EDGE_TYPES:
            raise ValueError(f"Edge type {edge.type!r} is not an ingestion edge type")

    by_type: dict[str, list[dict]] = {}
    for edge in _dedupe_edges(edges):
        props = edge.to_neo4j_props()
        if edge.weight > 1:
            props["weight"] = edge.weight
        by_type.setdefault(edge.type, []).append(
            {"source": edge.source_id, "target": edge.target_id, "props": props}
        )

    written: dict[str, int] = {}
    with get_session() as session:
        for edge_type, rows in by_type.items():
            count = 0
            for batch in _batches(rows, get_config().write_batch_size):
                result = session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:GraphNode {{id: row.source}}) "
                    f"MATCH (b:GraphNode {{id: row.target}}) "
                    f"MERGE (a)-[r:{edge_type}]->(b) "
                    f"SET r += row.props "
                    f"RETURN count(r) AS c",
                    rows=batch,
                )
                count += result.single()["c"]
            expected = len(rows)
            if count != expected:
                samples = _diagnose_missing(session, rows)
                raise WriteReconciliationError(edge_type, expected, count, samples)
            written[edge_type] = count
    return written


def write_linker_edges(edges: list[GraphEdge]) -> dict[str, int]:
    """Linker-only write path; MERGE key is (source, type, target, detected_by)."""
    groups: dict[tuple, list[dict]] = {}
    for edge in edges:
        if edge.type not in LINKER_EDGE_TYPES:
            raise ValueError(f"Edge type {edge.type!r} is not a linker edge type")
        if edge.created_by != "linker" or not edge.detected_by or not edge.link_run_id:
            raise ValueError(f"Linker edge {edge.type} missing provenance fields")
        source_label = getattr(edge, "source_label", "GraphNode")
        target_label = getattr(edge, "target_label", "GraphNode")
        groups.setdefault((edge.type, source_label, target_label), []).append({
            "source": edge.source_id, "target": edge.target_id,
            "detected_by": edge.detected_by, "props": edge.to_neo4j_props(),
        })

    written: dict[str, int] = {}
    with get_session() as session:
        for (edge_type, src_label, dst_label), rows in groups.items():
            count = 0
            for batch in _batches(rows, get_config().write_batch_size):
                result = session.run(
                    f"UNWIND $rows AS row "
                    f"MATCH (a:{src_label} {{id: row.source}}) "
                    f"MATCH (b:{dst_label} {{id: row.target}}) "
                    f"MERGE (a)-[r:{edge_type} {{detected_by: row.detected_by}}]->(b) "
                    # Temporal edges: MERGE preserves the
                    # relationship across runs, so first_seen_at survives
                    # every relink until the edge truly disappears.
                    f"ON CREATE SET r.first_seen_at = $now "
                    f"SET r += row.props "
                    f"RETURN count(r) AS c",
                    rows=batch, now=_utcnow(),
                )
                count += result.single()["c"]
            expected = len(rows)
            if count != expected:
                samples = _diagnose_missing(session, rows)
                raise WriteReconciliationError(edge_type, expected, count, samples)
            written[edge_type] = written.get(edge_type, 0) + count
    return written


def update_repo_stats(repo_id: str) -> None:
    with get_session() as session:
        session.run(
            "MATCH (n:GraphNode {repo_id: $repo_id}) WITH count(n) AS nc "
            "OPTIONAL MATCH (a:GraphNode {repo_id: $repo_id})-[r]->(b:GraphNode {repo_id: $repo_id}) "
            "WITH nc, count(r) AS ec "
            "MATCH (repo:Repo {id: $repo_id}) "
            "SET repo.node_count = nc, repo.edge_count = ec, repo.updated_at = $now",
            repo_id=repo_id, now=_utcnow(),
        )


FAILURE_STATES = ("failed_clean", "failed_partial")


def set_repo_lifecycle(repo_id: str, state: str, error: str = "") -> None:
    """Lifecycle transitions are written only by the job system (design §6.3).

    Failures MERGE rather than MATCH: a refresh that clears the old graph and
    then dies before the write has no Repo node left, and a repo that silently
    vanishes is worse than one visibly parked in failed_partial.
    """
    if state not in REPO_STATES:
        raise ValueError(f"Unknown lifecycle state {state!r}")
    clause = ("MERGE (repo:GraphNode:Repo {id: $repo_id}) "
              "ON CREATE SET repo.repo_id = $repo_id, repo.type = 'Repo', "
              "  repo.name = $repo_id, repo.label = $repo_id, "
              "  repo.created_at = $now "
              if state in FAILURE_STATES
              else "MATCH (repo:Repo {id: $repo_id}) ")
    with get_session() as session:
        session.run(
            clause +
            "SET repo.lifecycle_state = $state, repo.lifecycle_error = $error, "
            "repo.updated_at = $now",
            repo_id=repo_id, state=state, error=error, now=_utcnow(),
        )


def create_or_update_job(job_id: str, repo_id: str, status: str,
                         progress: int, message: str, error: str = None) -> None:
    with get_session() as session:
        session.run(
            "MERGE (j:IngestionJob {id: $job_id}) "
            "ON CREATE SET j.created_at = $now "
            "SET j.repo_id = $repo_id, j.status = $status, j.progress = $progress, "
            "j.message = $message, j.error = $error, j.updated_at = $now",
            job_id=job_id, repo_id=repo_id, status=status,
            progress=progress, message=message, error=error, now=_utcnow(),
        )
