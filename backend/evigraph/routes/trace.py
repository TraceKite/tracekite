"""VQ1 cross-repo trace: bounded path enumeration with per-hop confidence
predicate — never shortestPath (design §7 VQ1)."""

import logging

from fastapi import APIRouter, HTTPException, Query

from evigraph.config import settings
from evigraph.db.neo4j_client import get_session
from evigraph.services.graph_writer import LINKER_EDGE_TYPES
from evigraph.services.linker.confidence_math import path_confidence
from evigraph.utils import rendezvous_ids as rid

logger = logging.getLogger(__name__)
router = APIRouter()

# Directional hops for the service altitude.
TRACE_EDGE_TYPES = "ROUTES_TO|CALLS_SERVICE"

# Flow altitude (VQ3/lineage): a publish/consume chain is
# (a)-[:PUBLISHES_TO]->(topic)<-[:CONSUMES_FROM]-(b) — the consume hop points
# the wrong way for a directed pattern, so flow traces walk undirected and a
# per-hop predicate enforces flow semantics instead: "against" types
# (CONSUMES_FROM, READS_FROM) must be traversed from the rendezvous side.
FLOW_EDGE_TYPES = ("ROUTES_TO|CALLS_SERVICE|PUBLISHES_TO|CONSUMES_FROM"
                   "|FANS_OUT_TO|WRITES_TO|READS_FROM")
_AGAINST_TYPES = "['CONSUMES_FROM', 'READS_FROM']"
_FLOW_DIRECTION_PREDICATE = (
    "all(i IN range(0, size(relationships(p)) - 1) WHERE "
    f"  (type(relationships(p)[i]) IN {_AGAINST_TYPES} "
    "     AND endNode(relationships(p)[i]) = nodes(p)[i]) "
    f"  OR (NOT type(relationships(p)[i]) IN {_AGAINST_TYPES} "
    "     AND startNode(relationships(p)[i]) = nodes(p)[i]))")


def _resolve_service(session, query: str) -> tuple[str | None, list[str]]:
    """Exact id/name match, then case-insensitive name; suggestions on miss."""
    row = session.run(
        "MATCH (s:Service) WHERE s.id = $q OR s.name = $q "
        "RETURN s.id AS id ORDER BY s.id LIMIT 1",
        q=query,
    ).single()
    if row:
        return row["id"], []
    row = session.run(
        "MATCH (s:Service) WHERE toLower(s.name) = toLower($q) "
        "RETURN s.id AS id ORDER BY s.id LIMIT 1",
        q=query,
    ).single()
    if row:
        return row["id"], []
    suggestions = session.run(
        "MATCH (s:Service) RETURN s.name AS name ORDER BY s.name LIMIT 20",
    ).data()
    return None, [r["name"] for r in suggestions if r["name"]]


@router.get("/api/v2/trace")
async def trace(from_service: str = Query(..., min_length=1),
                to_service: str = Query(..., min_length=1),
                min_confidence: float = Query(0.6, ge=0.0, le=1.0),
                max_hops: int = Query(6, ge=1, le=8),
                k: int = Query(3, ge=1, le=10),
                altitude: str = Query("service", pattern="^(service|code)$"),
                via: str = Query("service", pattern="^(service|flow)$")):
    with get_session() as session:
        from_id, from_suggestions = _resolve_service(session, from_service)
        to_id, to_suggestions = _resolve_service(session, to_service)
        if from_id is None or to_id is None:
            raise HTTPException(status_code=404, detail={
                "error": "service_not_found",
                "from_resolved": from_id, "to_resolved": to_id,
                "suggestions": from_suggestions or to_suggestions,
            })

        if via == "flow":
            pattern = f"MATCH p = (a)-[:{FLOW_EDGE_TYPES}*1..{int(max_hops)}]-(b) "
            direction = f"AND {_FLOW_DIRECTION_PREDICATE} "
        else:
            pattern = f"MATCH p = (a)-[:{TRACE_EDGE_TYPES}*1..{int(max_hops)}]->(b) "
            direction = ""

        # Enumeration is capped before sorting: a dense service graph has
        # exponentially many <=8-hop paths, and ORDER BY ... LIMIT k alone
        # would materialize all of them first.
        scan_cap = int(settings.trace_max_paths)
        result = session.run(
            f"MATCH (a:Service {{id: $from_id}}), (b:Service {{id: $to_id}}) "
            + pattern +
            "WHERE all(r IN relationships(p) WHERE "
            "  coalesce(r.status, 'active') = 'active' "
            "  AND coalesce(r.min_confidence, r.confidence, 0) >= $minc) "
            + direction +
            "WITH p LIMIT $scan_cap "
            "WITH p, [r IN relationships(p) | "
            "  coalesce(r.min_confidence, r.confidence, 0)] AS confs "
            "RETURN [n IN nodes(p) | {id: n.id, name: coalesce(n.name, n.id), "
            "  labels: labels(n)}] AS nodes, "
            "[r IN relationships(p) | {type: type(r), confidence: r.confidence, "
            "  min_confidence: r.min_confidence, max_confidence: r.max_confidence, "
            "  via: r.via, weight: r.weight, path_prefix: r.path_prefix, "
            "  evidence: r.evidence, evidence_edge_ids: r.evidence_edge_ids}] AS edges, "
            "reduce(m = 1.0, c IN confs | CASE WHEN c < m THEN c ELSE m END) AS path_min "
            "ORDER BY size(nodes) ASC, path_min DESC LIMIT $k",
            from_id=from_id, to_id=to_id, minc=min_confidence, k=int(k),
            scan_cap=scan_cap,
        ).data()

        # Compounded in core, not in cypher: a 6-hop path at 0.9 per hop
        # is a 0.53 path, and both surfaces must agree on that number.
        paths = [{"nodes": row["nodes"], "edges": row["edges"],
                  "min_confidence": row["path_min"],
                  "confidence": path_confidence([
                      (e.get("confidence") or 0.0,
                       e.get("min_confidence") or e.get("confidence") or 0.0,
                       e.get("max_confidence") or e.get("confidence") or 0.0)
                      for e in row["edges"]])}
                 for row in result]
        if altitude == "code":
            _attach_crossings(session, paths)

        warnings = _staleness_warnings(session)
    if not paths:
        warnings.append({"kind": "no_path",
                         "detail": "No path at this confidence; try lowering "
                                   "min_confidence or rebuilding links"})
    return {"from": from_id, "to": to_id, "paths": paths,
            "altitude": altitude, "via": via, "warnings": warnings}


@router.get("/api/v2/topics")
async def list_topics(limit: int = Query(200, ge=1, le=500)):
    """VQ3 inventory: every Topic with its publisher/consumer counts."""
    with get_session() as session:
        rows = session.run(
            "MATCH (t:Topic) "
            "OPTIONAL MATCH (t)<-[p:PUBLISHES_TO]-() "
            "OPTIONAL MATCH (t)<-[c:CONSUMES_FROM]-() "
            "OPTIONAL MATCH (t)<-[d:DECLARES_TOPIC]-() "
            "RETURN t.id AS id, t.key AS key, t.name AS name, "
            "t.system AS system, t.redacted AS redacted, "
            "count(DISTINCT p) AS publishers, count(DISTINCT c) AS consumers, "
            "count(DISTINCT d) AS declarations "
            "ORDER BY publishers + consumers DESC LIMIT $limit",
            limit=limit).data()
    return {"topics": rows, "total": len(rows)}


@router.get("/api/v2/topics/chain")
async def topic_chain(key: str = Query(..., min_length=3, max_length=300),
                      min_confidence: float = Query(0.6, ge=0.0, le=1.0),
                      limit: int = Query(200, ge=1, le=500)):
    """VQ3 flagship: publisher -> topic -> consumer for one topic, plus any
    SNS->SQS fan-out one hop downstream."""
    node_id = rid.topic_id(key)
    with get_session() as session:
        def _side(edge_type: str, target: str = "t") -> list[dict]:
            # A hot topic can have hundreds of consumers; bound each side so
            # one popular topic cannot return the whole estate.
            return session.run(
                f"MATCH ({target}:Topic {{id: $id}})<-[r:{edge_type}]-(n) "
                "WHERE coalesce(r.status, 'active') = 'active' "
                "AND coalesce(r.min_confidence, r.confidence, 0) >= $minc "
                "RETURN n.id AS id, coalesce(n.name, n.id) AS name, "
                "labels(n) AS labels, r.confidence AS confidence, "
                "r.match_type AS match_type, r.service AS service, "
                "r.source_repo_id AS repo_id, r.evidence AS evidence "
                "ORDER BY r.confidence DESC LIMIT $limit",
                id=node_id, minc=min_confidence, limit=limit).data()

        publishers = _side("PUBLISHES_TO")
        consumers = _side("CONSUMES_FROM")
        declarations = _side("DECLARES_TOPIC")
        fan_out = session.run(
            "MATCH (t:Topic {id: $id})-[r:FANS_OUT_TO]->(d:Topic) "
            "OPTIONAL MATCH (d)<-[c:CONSUMES_FROM]-(n) "
            "RETURN d.key AS downstream, collect(DISTINCT "
            "{id: n.id, service: c.service, repo_id: c.source_repo_id}) "
            "AS consumers", id=node_id).data()
    return {"topic": key, "publishers": publishers, "consumers": consumers,
            "declarations": declarations,
            "fan_out": [f for f in fan_out if f["downstream"]]}


def _staleness_warnings(session) -> list[dict]:
    """Design principle 7: an answer states what it cannot see. A trace over
    links older than the newest ingest is not wrong, it is out of date, and the
    caller has no other way to know."""
    warnings: list[dict] = []
    stale = [record["id"] for record in session.run(
        "MATCH (r:Repo) WHERE r.lifecycle_state IN ['ingested', 'linked'] "
        "AND (r.linked_at IS NULL OR r.linked_at < r.updated_at) "
        "RETURN r.id AS id LIMIT 50",
    )]
    if stale:
        warnings.append({
            "kind": "links_stale",
            "detail": f"{len(stale)} repo(s) ingested since the last link run; "
                      f"paths through them may be missing",
            "repo_ids": stale,
        })
    unlinked = session.run(
        "MATCH (r:Repo) WHERE r.lifecycle_state = 'failed_partial' "
        "RETURN count(r) AS c",
    ).single()["c"]
    if unlinked:
        warnings.append({
            "kind": "repos_failed_partial",
            "detail": f"{unlinked} repo(s) failed mid-ingest and are excluded "
                      f"from linking; their edges are absent",
        })
    return warnings


def _attach_crossings(session, paths: list[dict]) -> None:
    for path in paths:
        refs = []
        for edge in path["edges"]:
            for ref in edge.get("evidence_edge_ids") or []:
                parts = ref.split("|", 2)
                # Edge type comes from the ref and must pass the linker
                # allowlist before interpolation into the cypher pattern.
                if len(parts) == 3 and parts[1] in LINKER_EDGE_TYPES:
                    refs.append({"src": parts[0], "type": parts[1],
                                 "dst": parts[2]})
        if not refs:
            path["crossings"] = []
            continue
        crossings = []
        for edge_type in sorted({ref["type"] for ref in refs}):
            batch = [ref for ref in refs if ref["type"] == edge_type]
            rows = session.run(
                f"UNWIND $refs AS ref "
                f"MATCH (a:GraphNode {{id: ref.src}})-[r:{edge_type}]->"
                "(b {id: ref.dst}) "
                "RETURN a.id AS call_site, a.path AS source_path, "
                "b.id AS contract, b.method AS method, "
                "b.path_template AS path_template, r.confidence AS confidence, "
                "r.evidence AS evidence, r.claim_key AS claim_key",
                refs=batch,
            ).data()
            crossings.extend(rows)
        path["crossings"] = crossings
