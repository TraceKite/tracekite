from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class IngestRepoRequest(BaseModel):
    """Request body for repo ingestion endpoint."""
    github_url: str = Field(..., description="GitHub repository URL")
    branch: Optional[str] = Field(default=None, description="Branch to clone (default: repo default)")
    github_token: Optional[str] = Field(default=None, description="GitHub personal access token for private repos")
    refresh: bool = Field(default=False, description="Force re-ingestion if repo already exists")


class IngestRepoResponse(BaseModel):
    """Response from repo ingestion endpoint."""
    job_id: str
    repo_id: str
    status: str
    message: str = "Ingestion queued"


class JobStatusResponse(BaseModel):
    """Response for job status endpoint."""
    job_id: str
    repo_id: str
    status: str  # queued, running, completed, failed
    progress: int = Field(default=0, ge=0, le=100)
    message: str = ""
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RepoSummary(BaseModel):
    """Summary of an ingested repository."""
    id: str
    name: str
    owner: str
    repo: str
    github_url: str
    branch: str
    last_ingested_at: Optional[datetime] = None
    ingestion_status: str
    lifecycle_state: Optional[str] = None
    head_commit_sha: Optional[str] = None
    node_count: int = 0
    edge_count: int = 0
    parse_coverage: Optional[dict] = None
    claims_by_kind: Optional[dict] = None
    linked_at: Optional[datetime] = None


class RepoListResponse(BaseModel):
    """Response for listing repos."""
    repos: list[RepoSummary]


class GraphNode(BaseModel):
    """A node in the graph response."""
    id: str
    type: str
    label: str
    name: str
    path: Optional[str] = None
    language: Optional[str] = None
    size: int = 5
    group: str = ""
    metadata: dict = Field(default_factory=dict)


class GraphLink(BaseModel):
    """A link/edge in the graph response."""
    source: str
    target: str
    type: str
    label: str
    value: int = 1
    confidence: float = 1.0
    origin: Optional[str] = None
    detected_by: Optional[str] = None


class GraphStats(BaseModel):
    """Statistics for the graph."""
    total_nodes: int = 0
    total_edges: int = 0
    node_types: dict[str, int] = Field(default_factory=dict)
    edge_types: dict[str, int] = Field(default_factory=dict)
    files: int = 0
    apis: int = 0
    dependencies: int = 0
    external_systems: int = 0


class GraphResponse(BaseModel):
    """Response for graph data endpoint."""
    repo: Optional[RepoSummary] = None
    stats: GraphStats
    nodes: list[GraphNode]
    links: list[GraphLink]


class SearchResult(BaseModel):
    """A single search result."""
    id: str
    type: str
    label: str
    path: Optional[str] = None
    score: float = 1.0


class SearchResponse(BaseModel):
    """Response for node search endpoint."""
    results: list[SearchResult]


class NodeDetail(BaseModel):
    """Detailed information about a single node."""
    node: GraphNode
    incoming: list[dict] = Field(default_factory=list)
    outgoing: list[dict] = Field(default_factory=list)
    neighbors: list[dict] = Field(default_factory=list)
    code_snippet: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    neo4j: str = "unknown"
    # Lets the UI skip the token prompt when reads are open. /health is public,
    # and this leaks no secret -- only whether a credential is required.
    anonymous_reads: bool = False
    auth_required_for_writes: bool = True
