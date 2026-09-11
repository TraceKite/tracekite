import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from tracekite.models.api_models import GraphResponse, SearchResponse, NodeDetail
from tracekite.services.graph_reader import (
    get_graph, search_nodes, get_node_details, get_neighbors,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/repos/{repo_id}/graph", response_model=GraphResponse)
async def get_repo_graph(
    repo_id: str,
    view: str = Query(default="overview", description="Graph view mode"),
    node_types: Optional[str] = Query(default=None, description="Comma-separated node types"),
    edge_types: Optional[str] = Query(default=None, description="Comma-separated edge types"),
    search: Optional[str] = Query(default=None, description="Search query"),
    limit: int = Query(default=300, ge=1, le=500),
    focus_node_id: Optional[str] = Query(default=None, description="Focus node for impact view"),
    depth: int = Query(default=2, ge=1, le=5),
):
    """Get graph data for a repository."""
    try:
        node_types_list = node_types.split(",") if node_types else None
        edge_types_list = edge_types.split(",") if edge_types else None
        
        graph = get_graph(
            repo_id=repo_id,
            view=view,
            node_types=node_types_list,
            edge_types=edge_types_list,
            search=search,
            limit=limit,
            focus_node_id=focus_node_id,
            depth=depth,
        )
        return graph
    except Exception as e:
        logger.error("Failed to get graph for %s: %s", repo_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/repos/{repo_id}/search")
async def search_repo_nodes(
    repo_id: str,
    q: str = Query(..., description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Search for nodes in a repository."""
    try:
        results = search_nodes(repo_id, q, limit)
        return SearchResponse(results=results)
    except Exception as e:
        logger.error("Search failed for %s: %s", repo_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/repos/{repo_id}/nodes/{node_id}")
async def get_node_detail(repo_id: str, node_id: str):
    """Get detailed information about a specific node."""
    try:
        detail = get_node_details(repo_id, node_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get node details: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/repos/{repo_id}/nodes/{node_id}/neighbors")
async def get_node_neighbors(
    repo_id: str,
    node_id: str,
    depth: int = Query(default=1, ge=1, le=3),
):
    """Get neighbors of a node."""
    try:
        return get_neighbors(repo_id, node_id, depth)
    except Exception as e:
        logger.error("Failed to get neighbors: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
