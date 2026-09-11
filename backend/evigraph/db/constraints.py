"""Schema DDL and repo deletion (design impl §2.4 verbatim; §5.3 deletion).

Deletion order matters: linker edges anchored on this repo's nodes go first,
then batched node deletion, then rendezvous orphan GC.
"""

import logging

from evigraph.db.neo4j_client import get_session
from evigraph.services.graph_writer import RENDEZVOUS_LABELS

logger = logging.getLogger(__name__)

DDL_STATEMENTS = [
    # Layer 0
    "CREATE CONSTRAINT graphnode_id  IF NOT EXISTS FOR (n:GraphNode)     REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT repo_id       IF NOT EXISTS FOR (r:Repo)          REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT job_id        IF NOT EXISTS FOR (j:IngestionJob)  REQUIRE j.id IS UNIQUE",
    "CREATE INDEX node_repo_type     IF NOT EXISTS FOR (n:GraphNode)     ON (n.repo_id, n.type)",
    "CREATE INDEX claim_kind_key     IF NOT EXISTS FOR (c:ContractClaim) ON (c.kind, c.key)",
    "CREATE INDEX claim_repo         IF NOT EXISTS FOR (c:ContractClaim) ON (c.repo_id)",
    "CREATE INDEX endpoint_match     IF NOT EXISTS FOR (e:ApiEndpoint)   ON (e.http_method, e.path_template)",
    "CREATE INDEX dependency_purl    IF NOT EXISTS FOR (d:Dependency)    ON (d.purl)",
    "CREATE INDEX symbol_uid         IF NOT EXISTS FOR (n:GraphNode)     ON (n.symbol_uid)",
    # Layer 1 — one unique constraint per label (MERGE must be index-backed)
    "CREATE CONSTRAINT lib_id   IF NOT EXISTS FOR (n:Library)           REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic)             REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT dataset_id IF NOT EXISTS FOR (n:Dataset)         REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT op_id    IF NOT EXISTS FOR (n:ContractOperation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT http_id  IF NOT EXISTS FOR (n:HttpContract)      REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT svcn_id  IF NOT EXISTS FOR (n:ServiceName)       REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT cfg_id   IF NOT EXISTS FOR (n:ConfigKey)         REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT team_id  IF NOT EXISTS FOR (n:Team)              REQUIRE n.id IS UNIQUE",
    "CREATE INDEX topic_name    IF NOT EXISTS FOR (n:Topic)             ON (n.name)",
    "CREATE INDEX svcname_name  IF NOT EXISTS FOR (n:ServiceName)       ON (n.name)",
    # Layer 2
    "CREATE CONSTRAINT service_id IF NOT EXISTS FOR (n:Service)         REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT linkrun_id IF NOT EXISTS FOR (n:LinkRun)         REQUIRE n.id IS UNIQUE",
    # Relationship indexes: the stale-edge sweep and the service map both
    # filter on r.created_by, which is a full relationship scan without these.
    "CREATE INDEX rel_created_by_calls IF NOT EXISTS FOR ()-[r:CALLS_SERVICE]-() ON (r.created_by)",
    "CREATE INDEX rel_created_by_routes IF NOT EXISTS FOR ()-[r:ROUTES_TO]-() ON (r.created_by)",
    "CREATE INDEX rel_created_by_built IF NOT EXISTS FOR ()-[r:BUILT_FROM]-() ON (r.created_by)",
    "CREATE INDEX rel_link_run_invokes IF NOT EXISTS FOR ()-[r:INVOKES]-() ON (r.link_run_id)",
    "CREATE INDEX rel_link_run_resolved IF NOT EXISTS FOR ()-[r:RESOLVED_TO]-() ON (r.link_run_id)",
    # Lifecycle filter used by load_claims and the staleness warnings.
    "CREATE INDEX repo_lifecycle IF NOT EXISTS FOR (r:Repo) ON (r.lifecycle_state)",
    # Global search
    "CREATE FULLTEXT INDEX code_search IF NOT EXISTS "
    "FOR (n:Class|Interface|Method|Function|ApiEndpoint|Config|Dependency|Topic|Library|Service) "
    "ON EACH [n.name, n.label, n.path, n.signature]",
    # Post-migration cleanup (edge_repo_type_idx is meaningless after typed edges)
    "DROP INDEX edge_repo_type_idx IF EXISTS",
]


def create_constraints() -> None:
    """Apply all schema DDL; idempotent."""
    with get_session() as session:
        for statement in DDL_STATEMENTS:
            try:
                session.run(statement).consume()
            except Exception as exc:
                logger.error("DDL failed: %s -- %s", statement[:80], exc)
                raise
    logger.info("Schema DDL applied (%d statements)", len(DDL_STATEMENTS))


def get_repo_claim_keys(repo_id: str) -> list[str]:
    """Distinct claim keys for a repo — captured before deletion for delta linking."""
    with get_session() as session:
        result = session.run(
            "MATCH (c:ContractClaim {repo_id: $repo_id}) RETURN DISTINCT c.key AS key",
            repo_id=repo_id,
        )
        return [record["key"] for record in result if record["key"]]


def clear_repo_graph(repo_id: str) -> dict:
    """Remove a repo's subgraph safely: linker edges, then nodes, then orphan GC."""
    counts = {}
    with get_session() as session:
        result = session.run(
            "MATCH (n:GraphNode {repo_id: $repo_id})-[r]-() "
            "WHERE r.created_by = 'linker' "
            "CALL { WITH r DELETE r } IN TRANSACTIONS OF 10000 ROWS",
            repo_id=repo_id,
        )
        counts["linker_edges_deleted"] = result.consume().counters.relationships_deleted

        result = session.run(
            "MATCH (n:GraphNode {repo_id: $repo_id}) "
            "CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS",
            repo_id=repo_id,
        )
        summary = result.consume().counters
        counts["nodes_deleted"] = summary.nodes_deleted
        counts["edges_deleted"] = summary.relationships_deleted

        result = session.run(
            "MATCH (j:IngestionJob {repo_id: $repo_id}) DETACH DELETE j",
            repo_id=repo_id,
        )
        counts["jobs_deleted"] = result.consume().counters.nodes_deleted

    counts["rendezvous_gcd"] = gc_orphan_rendezvous()
    logger.info("Cleared repo %s: %s", repo_id, counts)
    return counts


def gc_orphan_rendezvous() -> int:
    """Delete rendezvous/Service nodes with no remaining relationships."""
    total = 0
    with get_session() as session:
        for label in RENDEZVOUS_LABELS + ("Service",):
            result = session.run(
                f"MATCH (n:{label}) WHERE NOT (n)--() "
                f"CALL {{ WITH n DELETE n }} IN TRANSACTIONS OF 10000 ROWS",
            )
            total += result.consume().counters.nodes_deleted
    return total
