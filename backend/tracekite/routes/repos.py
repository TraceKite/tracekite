"""Repository management routes: ingest, list, get, delete, refresh.

All mutations flow through the job queue — routes never spawn raw threads.
"""

import logging

from fastapi import APIRouter, HTTPException

from tracekite.config import settings
from tracekite.models.api_models import (
    IngestRepoRequest, IngestRepoResponse, RepoListResponse,
)
from tracekite.services.graph_reader import get_repo, list_repos
from tracekite.services.job_queue import job_queue
from tracekite.utils.hashing import extract_git_host, generate_repo_id, normalize_github_url

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/repos/ingest", response_model=IngestRepoResponse, status_code=202)
async def ingest_repo(request: IngestRepoRequest):
    """Queue ingestion of a repository."""
    try:
        normalized_url, owner, repo_name = normalize_github_url(request.github_url)
        host = extract_git_host(normalized_url)
        repo_id = generate_repo_id(owner, repo_name, host)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if host not in settings.allowed_hosts_list():
        raise HTTPException(status_code=400,
                            detail=f"Git host {host!r} is not allowlisted")

    job_type = "refresh" if request.refresh else "ingest"
    job_id = job_queue.submit(job_type, repo_id, payload={
        # The normalized URL is what gets cloned and recorded — never the raw
        # user string, or the two can disagree about which host was reached.
        "github_url": normalized_url,
        "branch": request.branch,
        "github_token": request.github_token,
        "refresh": request.refresh,
    })
    return IngestRepoResponse(
        job_id=job_id, repo_id=repo_id, status="queued",
        message=f"{job_type} queued",
    )


@router.get("/api/repos", response_model=RepoListResponse)
async def list_repositories():
    return RepoListResponse(repos=list_repos())


@router.get("/api/repos/{repo_id}")
async def get_repository(repo_id: str):
    repo = get_repo(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    return repo


@router.delete("/api/repos/{repo_id}", status_code=202)
async def delete_repository_graph(repo_id: str):
    """Queue repository deletion (serialized through the linker lane)."""
    repo = get_repo(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    job_id = job_queue.submit("repo_delete", repo_id)
    return {"job_id": job_id, "repo_id": repo_id, "status": "queued",
            "message": "Repository deletion queued"}


@router.post("/api/repos/{repo_id}/refresh", status_code=202)
async def refresh_repository(repo_id: str):
    """Queue a refresh: re-clone, re-parse, then swap the graph."""
    repo = get_repo(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repository {repo_id} not found")
    job_id = job_queue.submit("refresh", repo_id, payload={
        "github_url": repo.github_url,
        "branch": repo.branch,
    })
    return {"job_id": job_id, "repo_id": repo_id, "status": "queued",
            "message": "Repository refresh queued"}
