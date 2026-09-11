"""Job-queue handlers binding job types to pipeline entry points."""

import logging

from evigraph.db.constraints import clear_repo_graph, get_repo_claim_keys
from evigraph.run_logging import run_context
from evigraph.services.graph_writer import create_or_update_job
from evigraph.services.ingestion_service import run_ingestion
from evigraph.services.job_queue import Job, JobQueue
from evigraph.services.repo_service import delete_repository

logger = logging.getLogger(__name__)


LINKER_REPO_ID = "__linker__"


def _enqueue_relink(reason: str) -> None:
    """Layer-1/2 are a cache of Layer-0; anything that changes Layer-0 must
    schedule a relink or the graph serves answers from deleted evidence.
    Submissions coalesce, so a burst of ingests yields one link run."""
    from evigraph.services.job_queue import job_queue

    job_id = job_queue.submit("link_full", LINKER_REPO_ID)
    logger.info("Queued link run %s (%s)", job_id, reason)


def _ingest(job: Job, refresh: bool) -> None:
    payload = job.payload
    run_ingestion(
        job.id,
        payload["github_url"],
        branch=payload.get("branch"),
        github_token=payload.get("github_token"),
        refresh=refresh,
    )
    _enqueue_relink(f"{job.type} of {job.repo_id}")


def _handle_ingest(job: Job) -> None:
    _ingest(job, refresh=bool(job.payload.get("refresh", False)))


def _handle_refresh(job: Job) -> None:
    _ingest(job, refresh=True)


def _linker():
    """Compose the application's linker: core driver over the Neo4j store.

    Choosing the backend is the server's job, not the linker's — this is the
    only place in the app that names one. Imports stay function-level because
    the linker package pulls in every resolver at import time.
    """
    from evigraph.services.linker import LinkerService
    from evigraph.services.linker_store import Neo4jLinkerStore

    return LinkerService(Neo4jLinkerStore(), on_run=_publish_run)


def _publish_run(run_id: str, counters: dict, timings) -> None:
    """Send one finished run's counters and timings wherever metrics go.

    Here rather than in the linker: choosing an exporter is the same kind of
    decision as choosing Neo4j, and this module is where the app makes them.
    """
    from evigraph.metrics_export import default_sink, export_run

    export_run(default_sink(), run_id=run_id, counters=counters,
               timings=timings)


def _handle_link_full(job: Job) -> None:
    create_or_update_job(job.id, job.repo_id, "running", 10,
                         "Linking: loading claims and resolving")
    with run_context(f"job_{job.id}"):
        counters = _linker().link_full()
    edges = counters.get("edges_written", 0)
    create_or_update_job(job.id, job.repo_id, "completed", 100,
                         f"Link run complete ({edges} edges)")


def _handle_link_delta(job: Job) -> None:
    create_or_update_job(job.id, job.repo_id, "running", 10,
                         "Delta link: checking claim fingerprints")
    with run_context(f"job_{job.id}"):
        counters = _linker().link_delta()
    if counters.get("skipped"):
        create_or_update_job(job.id, job.repo_id, "completed", 100,
                             "Delta link skipped: no claims changed")
        return
    edges = counters.get("edges_written", 0)
    create_or_update_job(
        job.id, job.repo_id, "completed", 100,
        f"Delta link complete ({counters.get('repos_changed', 0)} repos "
        f"changed, {edges} edges)")


def _handle_repo_delete(job: Job) -> None:
    create_or_update_job(job.id, job.repo_id, "running", 10, "Deleting repository")
    claim_keys = get_repo_claim_keys(job.repo_id)
    counts = clear_repo_graph(job.repo_id)
    delete_repository(job.repo_id)
    create_or_update_job(job.id, job.repo_id, "completed", 100,
                         f"Repository deleted ({counts.get('nodes_deleted', 0)} nodes)")
    if claim_keys:
        # Service-to-Service rollups are not anchored on this repo's nodes, so
        # clear_repo_graph cannot reach them; only a relink retires them.
        _enqueue_relink(f"delete of {job.repo_id} ({len(claim_keys)} claim keys)")


def register_all(queue: JobQueue) -> None:
    queue.register_handler("ingest", _handle_ingest)
    queue.register_handler("refresh", _handle_refresh)
    queue.register_handler("repo_delete", _handle_repo_delete)
    queue.register_handler("link_full", _handle_link_full)
    queue.register_handler("link_delta", _handle_link_delta)
