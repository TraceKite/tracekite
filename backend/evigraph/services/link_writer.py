"""Write path for linker-owned nodes and the LinkRun ledger (design §6.3)."""

import json
import logging

from evigraph.db.neo4j_client import get_session
from evigraph.services.graph_writer import RENDEZVOUS_LABELS, _batches, _utcnow

logger = logging.getLogger(__name__)

_WRITABLE_LABELS = set(RENDEZVOUS_LABELS)


def write_rendezvous_nodes(specs: list) -> int:
    groups: dict[str, list[dict]] = {}
    for spec in specs:
        if spec.label not in _WRITABLE_LABELS:
            raise ValueError(f"{spec.label!r} is not a rendezvous label")
        groups.setdefault(spec.label, []).append(
            {"id": spec.node_id, "props": spec.props})

    total = 0
    with get_session() as session:
        for label, rows in groups.items():
            for batch in _batches(rows, 500):
                result = session.run(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{label}:Rendezvous {{id: row.id}}) "
                    f"SET n += row.props, n.updated_at = $now "
                    f"RETURN count(n) AS c",
                    rows=batch, now=_utcnow(),
                )
                total += result.single()["c"]
    return total


def write_service_nodes(specs: list) -> int:
    rows = [{"id": s.service_id, "name": s.name, "repo_ids": s.repo_ids}
            for s in specs]
    gateway_ids = [s.service_id for s in specs if s.is_gateway]
    total = 0
    with get_session() as session:
        for batch in _batches(rows, 500):
            result = session.run(
                "UNWIND $rows AS row "
                "MERGE (n:Service {id: row.id}) "
                "SET n.name = row.name, n.repo_ids = row.repo_ids, "
                "    n.updated_at = $now "
                "RETURN count(n) AS c",
                rows=batch, now=_utcnow(),
            )
            total += result.single()["c"]
        if gateway_ids:
            session.run(
                "MATCH (n:Service) WHERE n.id IN $ids SET n:Gateway",
                ids=gateway_ids,
            ).consume()
    return total


def create_link_run(run_id: str, mode: str) -> None:
    with get_session() as session:
        session.run(
            "MERGE (l:LinkRun {id: $id}) "
            "SET l.mode = $mode, l.status = 'running', l.started_at = $now, "
            "    l.finished_at = null, l.error = ''",
            id=run_id, mode=mode, now=_utcnow(),
        ).consume()


def finish_link_run(run_id: str, status: str, counters: dict,
                    error: str = "") -> None:
    with get_session() as session:
        session.run(
            "MATCH (l:LinkRun {id: $id}) "
            "SET l.status = $status, l.finished_at = $now, "
            "    l.counters = $counters, l.error = $error",
            id=run_id, status=status, now=_utcnow(),
            counters=json.dumps(counters), error=error,
        ).consume()


def list_link_runs(limit: int = 10) -> list[dict]:
    with get_session() as session:
        result = session.run(
            "MATCH (l:LinkRun) RETURN properties(l) AS props "
            "ORDER BY l.started_at DESC LIMIT $limit",
            limit=limit,
        )
        runs = []
        for record in result:
            props = dict(record["props"])
            try:
                props["counters"] = json.loads(props.get("counters") or "{}")
            except (TypeError, ValueError):
                props["counters"] = {}
            runs.append(props)
        return runs


def delete_stale_linker_edges(current_run_id: str) -> int:
    with get_session() as session:
        result = session.run(
            "MATCH ()-[r]->() "
            "WHERE r.created_by = 'linker' "
            "AND coalesce(r.link_run_id, '') <> $run "
            "CALL { WITH r DELETE r } IN TRANSACTIONS OF 10000 ROWS",
            run=current_run_id,
        )
        deleted = result.consume().counters.relationships_deleted
    if deleted:
        logger.info("Deleted %d stale linker edges", deleted)
    return deleted


def stamp_repos_linked(repo_ids: list[str], run_id: str) -> None:
    if not repo_ids:
        return
    with get_session() as session:
        session.run(
            "MATCH (r:Repo) WHERE r.id IN $ids "
            "SET r.linked_at = $now, r.last_link_run_id = $run",
            ids=repo_ids, now=_utcnow(), run=run_id,
        ).consume()
