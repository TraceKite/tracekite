"""Linker control plane: rebuild, status, review queue,
impact queries (design §7)."""

import logging
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from adduce.db.neo4j_client import get_session
from adduce.services.job_queue import job_queue
from adduce.services.link_writer import list_link_runs
from adduce.utils import rendezvous_ids as rid


logger = logging.getLogger(__name__)

router = APIRouter()

# Which run counters represent something the linker REFUSED to resolve. The
# first version of this pattern silently dropped 16 of them — including
# `r7.unqualified`, normally the single largest recall gap in a real estate —
# so the review queue reported a comfortably short list of gaps that was not
# the truth. Every vocabulary a resolver actually uses for a decline is
# enumerated here; `tests/test_links_trace_routes.py` asserts no `ctx.count`
# decline name escapes it.
_DECLINE_COUNTER = re.compile(
    r"ambiguous|unresolved|unmatched|declined|rejected|skipped|dead_end"
    r"|below_floor|unminted|unlinked|unqualified|unattributed|unmapped"
    r"|fanout_exceeded|no_target|no_site_node|no_call_site_node"
    r"|no_consumer_identity|secret_ref|self_or_unknown|multi_declarer"
    r"|calls_self")

LINKER_REPO_ID = "__linker__"


@router.post("/api/v2/links/rebuild", status_code=202)
async def rebuild_links():
    job_id = job_queue.submit("link_full", LINKER_REPO_ID)
    return {"job_id": job_id, "status": "queued"}


@router.get("/api/v2/links/status")
async def links_status():
    runs = list_link_runs(limit=10)
    warnings = []
    with get_session() as session:
        result = session.run(
            "MATCH (r:Repo) WHERE r.lifecycle_state IN ['ingested', 'linked'] "
            "AND (r.linked_at IS NULL OR r.linked_at < r.updated_at) "
            "RETURN r.id AS id",
        )
        stale = [record["id"] for record in result]
    if stale:
        warnings.append({"kind": "links_stale",
                         "detail": f"{len(stale)} repo(s) ingested since last link run",
                         "repo_ids": stale})
    return {"runs": runs, "latest": runs[0] if runs else None,
            "warnings": warnings}


@router.post("/api/v2/links/delta", status_code=202)
async def delta_links():
    """Incremental relink: no-op when no repo's claims changed."""
    job_id = job_queue.submit("link_delta", LINKER_REPO_ID)
    return {"job_id": job_id, "status": "queued"}


@router.get("/api/v2/links/review")
async def review_queue(limit: int = Query(100, ge=1, le=500)):
    """Candidate edges awaiting review, plus every decline counter
    from the latest run — the counters ARE the missing-recall worklist."""
    with get_session() as session:
        rows = session.run(
            "MATCH (a)-[r]->(b) WHERE r.created_by = 'linker' "
            "AND r.status = 'candidate' "
            "RETURN a.id AS source, coalesce(a.name, a.id) AS source_name, "
            "type(r) AS type, b.id AS target, "
            "coalesce(b.name, b.id) AS target_name, "
            "r.confidence AS confidence, r.match_type AS match_type, "
            "r.detected_by AS detected_by, r.claim_key AS claim_key, "
            "r.evidence AS evidence "
            "ORDER BY r.confidence DESC LIMIT $limit",
            limit=limit).data()
        # A true total, so the UI can say "showing 100 of 412" instead of
        # implying the queue is exactly as long as one page.
        total = session.run(
            "MATCH ()-[r]->() WHERE r.created_by = 'linker' "
            "AND r.status = 'candidate' RETURN count(r) AS c").single()["c"]

    # The newest run may still be RUNNING, and a running run has no counters
    # yet — reading it would report "nothing was declined", which is the most
    # misleading answer this endpoint could give. Take the newest FINISHED run.
    finished = [run for run in list_link_runs(limit=10)
                if run.get("status") == "done" and run.get("counters")]
    counters = finished[0]["counters"] if finished else {}
    declines = {k: v for k, v in counters.items() if _DECLINE_COUNTER.search(k)}
    return {"candidates": rows, "decline_counters": declines,
            "counted_from_run": finished[0]["id"] if finished else None,
            "returned": len(rows), "total": total}


class ReviewDecision(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    type: str = Field(min_length=1, max_length=60)
    target: str = Field(min_length=1, max_length=500)
    decision: str = Field(pattern="^(promote|reject)$")
    note: str = Field(default="", max_length=500)
    # Which resolver tier priced the edge (e.g. "r7.hint_exact"). Optional,
    # but a decision that names it becomes a per-tier label E5's derivation
    # can pool; one that doesn't only counts globally.
    tier: str = Field(default="", pattern=r"^(r\d+\.\w+)?$")


@router.post("/api/v2/links/review/decide")
async def review_decide(body: ReviewDecision):
    """Apply an operator decision now AND persist it to the control plane so
    every future relink replays it (D6 promotions replay)."""
    from adduce.services.control_plane import append_promotion
    status = "active" if body.decision == "promote" else "rejected"
    with get_session() as session:
        result = session.run(
            f"MATCH (a {{id: $source}})-[r:{_safe_type(body.type)}]->"
            "(b {id: $target}) WHERE r.created_by = 'linker' "
            "SET r.status = $status, r.reviewed = true, "
            "r.review_note = $note RETURN count(r) AS c",
            source=body.source, target=body.target, status=status,
            note=body.note)
        updated = result.single()["c"]
    if not updated:
        raise HTTPException(404, "no linker edge matches that triple")
    append_promotion({"source": body.source, "type": body.type,
                      "target": body.target, "decision": body.decision,
                      "note": body.note, "tier": body.tier})
    return {"updated": updated, "status": status}


def _safe_type(edge_type: str) -> str:
    from adduce.services.graph_writer import LINKER_EDGE_TYPES
    if edge_type not in LINKER_EDGE_TYPES:
        raise HTTPException(400, f"unknown edge type {edge_type!r}")
    return edge_type


@router.get("/api/v2/links/deprecated")
async def deprecated_and_dead(limit: int = Query(200, ge=1, le=500)):
    """Deprecated contracts, and exposed contracts no one invokes
    (dead-endpoint candidates — absence of a consumer is a candidate fact,
    not proof, so they are reported, never deleted)."""
    with get_session() as session:
        deprecated = session.run(
            "MATCH (c:HttpContract) WHERE c.deprecated = true "
            "RETURN c.id AS id, c.method AS method, "
            "c.path_template AS path, c.service_scope AS scope "
            "ORDER BY c.service_scope, c.path_template LIMIT $limit",
            limit=limit).data()
        # DISTINCT matters: the pattern yields one row per EXPOSES edge, so a
        # contract exposed by three handlers was reported as three dead
        # endpoints — inflating the number the UI would headline.
        dead = session.run(
            "MATCH (c:HttpContract)<-[:EXPOSES]-() "
            "WHERE NOT (c)<-[:INVOKES]-() "
            "RETURN DISTINCT c.id AS id, c.method AS method, "
            "c.path_template AS path, c.service_scope AS scope "
            "ORDER BY c.service_scope, c.path_template LIMIT $limit",
            limit=limit).data()
    return {"deprecated": deprecated, "dead_candidates": dead}


@router.get("/api/v2/config/ownership")
async def config_ownership(name: str = Query(..., min_length=1, max_length=200)):
    """VQ4: who defines a config/env key, who reads it, and which teams own
    the repos on each side. Runs over claims directly — definition and read
    sites are facts even when no resolver joined them."""
    with get_session() as session:
        rows = session.run(
            "MATCH (c:GraphNode:ContractClaim) "
            "WHERE c.kind IN ['cfgdef', 'cfgread'] "
            "AND (c.key ENDS WITH (':' + $name) OR c.name = $name "
            "     OR c.key CONTAINS ('/' + $name)) "
            "OPTIONAL MATCH (r:Repo {id: c.repo_id})-[:OWNED_BY]->(t:Team) "
            "RETURN c.kind AS kind, c.key AS key, c.repo_id AS repo_id, "
            "c.path AS path, c.env_scope AS env_scope, "
            "collect(DISTINCT t.name) AS teams "
            "ORDER BY c.kind, c.repo_id LIMIT 500",
            name=name).data()
    definitions = [r for r in rows if r["kind"] == "cfgdef"]
    reads = [r for r in rows if r["kind"] == "cfgread"]
    return {"name": name, "definitions": definitions, "reads": reads,
            "owning_teams": sorted({t for r in rows for t in r["teams"] if t}),
            "orphaned": bool(reads and not definitions)}


@router.get("/api/v2/impact/library")
async def library_impact(key: str = Query(..., min_length=5, max_length=300)):
    """VQ2: who breaks when this library changes.

    `key` is a version-free purl (`pkg:maven/org.acme/billing-lib`). Version
    skew falls out of the per-edge versions on one rendezvous node.
    """
    node_id = rid.library_id(key)
    with get_session() as session:
        publishers = session.run(
            "MATCH (r:Repo)-[e:PUBLISHES]->(l:Library {id: $id}) "
            "RETURN r.id AS repo_id, e.version AS version",
            id=node_id).data()
        dependents = session.run(
            "MATCH (r:Repo)-[e:DEPENDS_ON]->(l:Library {id: $id}) "
            "WHERE coalesce(e.status, 'active') = 'active' "
            "RETURN r.id AS repo_id, e.version AS version, "
            "e.resolved AS resolved, e.scope AS scope, "
            "e.confidence AS confidence ORDER BY r.id",
            id=node_id).data()
    versions = sorted({d["version"] for d in dependents if d["version"]})
    return {"library": key, "publishers": publishers,
            "dependents": dependents,
            "distinct_versions": versions,
            "version_skew": len(versions) > 1}


@router.get("/api/v2/impact/repo/{repo_id}")
async def repo_impact(repo_id: str):
    """VQ2 from the repo side: what this repo publishes and who consumes it."""
    with get_session() as session:
        rows = session.run(
            "MATCH (r:Repo {id: $rid})-[:PUBLISHES]->(l:Library) "
            "OPTIONAL MATCH (d:Repo)-[e:DEPENDS_ON]->(l) "
            "WHERE coalesce(e.status, 'active') = 'active' "
            "RETURN l.key AS library, collect(DISTINCT {repo_id: d.id, "
            "version: e.version, resolved: e.resolved}) AS dependents",
            rid=repo_id).data()
    libraries = [{"library": row["library"],
                  "dependents": [d for d in row["dependents"] if d["repo_id"]]}
                 for row in rows]
    return {"repo_id": repo_id, "publishes": libraries,
            "blast_radius": sorted({d["repo_id"] for row in libraries
                                    for d in row["dependents"]})}
