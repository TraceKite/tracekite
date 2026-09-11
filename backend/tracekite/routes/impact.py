"""HTTP surface for estate map and code-bridge reads."""

from fastapi import APIRouter, Query

from tracekite.db.impact_reader import read_code_bridges, read_service_map

router = APIRouter()


@router.get("/api/v2/service-map")
async def service_map(
        min_confidence: float = Query(0.6, ge=0.0, le=1.0),
        limit: int = Query(500, ge=1, le=500)):
    return read_service_map(min_confidence, limit)


@router.get("/api/v2/code-bridges")
async def code_bridges(
        repos: str = Query(..., description="Comma-separated repo ids"),
        limit: int = Query(200, ge=1, le=500)):
    """Where the selected repositories actually touch, at code altitude.

    The per-repo graph is deliberately intra-repo: files, classes, endpoints of
    ONE codebase. Drawing several of those together produces disconnected
    islands, because nothing in that response crosses a repository boundary.

    What crosses is a rendezvous: a call site INVOKES a contract that another
    repo's endpoint EXPOSES. The contract is the join, so it is returned as a
    node and both halves as edges.

    The two endpoint nodes come back as well. They are the whole point of the
    query, and the caller's per-repo sample is capped -- a bridge whose call
    site fell outside that sample would otherwise dangle.
    """
    repo_ids = [repo.strip() for repo in repos.split(",") if repo.strip()]
    if not repo_ids:
        return {"nodes": [], "links": [], "repos": []}
    return read_code_bridges(repo_ids, limit)
