from fastapi import APIRouter
from adduce.models.api_models import HealthResponse
from adduce.config import settings
from adduce.db.neo4j_client import check_neo4j_health

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Check the health of the backend and its dependencies."""
    neo4j_ok = check_neo4j_health()
    return HealthResponse(
        status="ok" if neo4j_ok else "degraded",
        neo4j="ok" if neo4j_ok else "unavailable",
        anonymous_reads=(not settings.auth_enabled) or settings.allow_anonymous_reads,
        auth_required_for_writes=settings.auth_enabled,
    )


@router.get("/api/config")
async def client_config():
    """Operator-set limits the UI must honour.

    Served rather than hardcoded in the frontend so a deployment can raise or
    lower the cap without a rebuild, and so there is one source of truth when
    the UI's guardrail and the API's own ceilings need to agree.
    """
    return {
        "max_scope_repos": settings.max_scope_repos,
        "graph_detail_node_limit": settings.graph_detail_node_limit,
        # The service map truncates at this many edges; the picker warns as a
        # selection approaches it, because silently truncated output is the
        # failure this project exists to avoid.
        "service_map_edge_limit": 500,
    }
