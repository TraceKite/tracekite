"""Neo4j-backed implementation of the linker's storage port.

This is the only place a link run touches a database, and it sits outside
`linker/` on purpose: `linker/` is core and must stay importable without a
driver, a server, or a connection (architecture §2).

Writes delegate to `graph_writer`/`link_writer` rather than restating their
Cypher — one implementation, both surfaces. The two reads live here because
they existed nowhere else: they used to sit inside the linker, a layering
violation that has since been fixed.
"""

import hashlib
import json
import logging

from adduce.db.constraints import gc_orphan_rendezvous
from adduce.db.neo4j_client import get_session
from adduce.services import graph_writer, link_writer
from adduce.services.linker.base import ClaimRecord
from adduce.db.memory_store import claim_record

logger = logging.getLogger(__name__)

# Only repos that finished a write are linkable. A failed_partial repo has
# claims in the graph but an unknown fraction of its evidence nodes, so linking
# off it produces edges that look resolved and are silently incomplete.
LINKABLE_STATES = ("ingested", "linking", "linked")


class Neo4jLinkerStore:
    """Implements `LinkerStore` against the application's Neo4j session."""

    # --- reads ------------------------------------------------------------

    def load_claims(self) -> list[ClaimRecord]:
        records: list[ClaimRecord] = []
        with get_session() as session:
            result = session.run(
                "MATCH (r:Repo) WHERE r.lifecycle_state IN $states "
                "MATCH (c:GraphNode:ContractClaim {repo_id: r.id}) "
                "OPTIONAL MATCH (c)-[:EVIDENCED_BY]->(t:GraphNode) "
                "RETURN properties(c) AS props, t.id AS enode, t.type AS etype",
                states=list(LINKABLE_STATES),
            )
            for record in result:
                props = record["props"]
                try:
                    attrs = json.loads(props.get("metadata") or "{}")
                except (TypeError, ValueError):
                    attrs = {}
                # The same field mapping the in-memory and artifact readers
                # use. This store had its own copy, so it was the one reader
                # a new ClaimRecord field would silently default — and it is
                # the reader production runs.
                records.append(claim_record(
                    props.get("id", ""), props.get("repo_id", ""), props,
                    attrs, record["enode"], record["etype"] or ""))
        return records

    def unlinkable_repos(self) -> dict[str, str]:
        with get_session() as session:
            rows = session.run(
                "MATCH (r:Repo) WHERE NOT r.lifecycle_state IN $states "
                "RETURN r.id AS id, r.lifecycle_state AS state",
                states=list(LINKABLE_STATES)).data()
        return {row["id"]: row["state"] or "unknown" for row in rows}

    def claim_fingerprints(self) -> dict[str, str]:
        by_repo: dict[str, list[str]] = {}
        with get_session() as session:
            rows = session.run(
                "MATCH (c:GraphNode:ContractClaim) "
                "RETURN c.repo_id AS repo, c.id AS id")
            for row in rows:
                by_repo.setdefault(row["repo"], []).append(row["id"])
        return {repo: hashlib.sha256("\n".join(sorted(ids)).encode())
                .hexdigest()[:16] for repo, ids in by_repo.items()}

    def stored_fingerprints(self) -> dict[str, str]:
        with get_session() as session:
            rows = session.run(
                "MATCH (r:Repo) RETURN r.id AS id, "
                "r.claims_fingerprint AS fp").data()
        return {row["id"]: row["fp"] for row in rows}

    # --- writes -----------------------------------------------------------

    def store_fingerprints(self, fingerprints: dict[str, str]) -> None:
        rows = [{"id": repo, "fp": fp} for repo, fp in fingerprints.items()]
        with get_session() as session:
            session.run(
                "UNWIND $rows AS row MATCH (r:Repo {id: row.id}) "
                "SET r.claims_fingerprint = row.fp", rows=rows).consume()

    def create_link_run(self, run_id: str, mode: str) -> None:
        link_writer.create_link_run(run_id, mode=mode)

    def finish_link_run(self, run_id: str, status: str, counters: dict,
                        error: str | None = None) -> None:
        link_writer.finish_link_run(run_id, status, counters, error=error)

    def write_rendezvous_nodes(self, specs: list) -> int:
        return link_writer.write_rendezvous_nodes(specs)

    def write_service_nodes(self, specs: list) -> int:
        return link_writer.write_service_nodes(specs)

    def write_linker_edges(self, edges: list) -> dict[str, int]:
        return graph_writer.write_linker_edges(edges)

    def delete_stale_linker_edges(self, current_run_id: str) -> int:
        return link_writer.delete_stale_linker_edges(current_run_id)

    def stamp_repos_linked(self, repo_ids: list[str], run_id: str) -> None:
        link_writer.stamp_repos_linked(repo_ids, run_id)

    def gc_orphan_rendezvous(self) -> int:
        return gc_orphan_rendezvous()
