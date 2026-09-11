import logging
from fastapi import APIRouter, HTTPException
from tracekite.models.api_models import JobStatusResponse
from tracekite.db.neo4j_client import get_session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get the status of an ingestion job."""
    try:
        with get_session() as session:
            result = session.run(
                """
                MATCH (j:IngestionJob {id: $job_id})
                RETURN j.id AS job_id, j.repo_id AS repo_id, j.status AS status,
                       j.progress AS progress, j.message AS message,
                       j.error AS error, j.created_at AS created_at,
                       j.updated_at AS updated_at
                """,
                job_id=job_id,
            )
            record = result.single()
            
            if not record:
                raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
            
            return JobStatusResponse(
                job_id=record["job_id"],
                repo_id=record["repo_id"] or "",
                status=record["status"] or "unknown",
                progress=record["progress"] or 0,
                message=record["message"] or "",
                error=record["error"],
                created_at=record["created_at"],
                updated_at=record["updated_at"],
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get job status: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
