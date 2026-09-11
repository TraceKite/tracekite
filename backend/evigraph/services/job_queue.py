"""In-process job queue (design §6.3): bounded ingest lane + serialized linker lane.

Job types: ingest, refresh, repo_delete, link_full, link_delta.
Ingest/refresh run on a small worker pool with a per-repo mutex; everything
that touches shared Layer-1/2 state (linking, deletes) runs on one thread.
"""

import logging
import queue
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from evigraph.config import settings
from evigraph.services.graph_writer import create_or_update_job

logger = logging.getLogger(__name__)

INGEST_LANE = ("ingest", "refresh")
LINKER_LANE = ("repo_delete", "link_full", "link_delta")
JOB_TYPES = INGEST_LANE + LINKER_LANE
# Jobs that rewrite shared Layer-1/2 state and must not overlap an ingest.
EXCLUSIVE_JOBS = frozenset(LINKER_LANE)

_SENTINEL = None


@dataclass
class Job:
    id: str
    type: str
    repo_id: str
    payload: dict = field(default_factory=dict)


class _GraphLock:
    """Many concurrent ingests, or one exclusive linker run — never both.

    A link run snapshots every claim in the graph and then deletes edges from
    prior runs. Overlapping it with an in-flight ingest links off a half-written
    repo and can delete edges the ingest is still producing evidence for.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._shared = 0
        self._exclusive = False

    def acquire_shared(self) -> None:
        with self._cond:
            while self._exclusive:
                self._cond.wait()
            self._shared += 1

    def release_shared(self) -> None:
        with self._cond:
            self._shared -= 1
            if self._shared == 0:
                self._cond.notify_all()

    def acquire_exclusive(self) -> None:
        with self._cond:
            while self._exclusive or self._shared > 0:
                self._cond.wait()
            self._exclusive = True

    def release_exclusive(self) -> None:
        with self._cond:
            self._exclusive = False
            self._cond.notify_all()

    @contextmanager
    def shared(self):
        self.acquire_shared()
        try:
            yield
        finally:
            self.release_shared()

    @contextmanager
    def exclusive(self):
        self.acquire_exclusive()
        try:
            yield
        finally:
            self.release_exclusive()


class JobQueue:
    def __init__(self, ingest_workers: int | None = None):
        self._ingest_workers = max(
            1, ingest_workers if ingest_workers is not None
            else settings.ingest_workers)
        self._ingest_q: queue.Queue = queue.Queue()
        self._linker_q: queue.Queue = queue.Queue()
        self._pending: dict[tuple[str, str], str] = {}
        self._pending_lock = threading.Lock()
        self._repo_locks: dict[str, threading.Lock] = {}
        self._repo_locks_guard = threading.Lock()
        self._graph_lock = _GraphLock()
        self._handlers: dict[str, Callable[[Job], None]] = {}
        self._threads: list[threading.Thread] = []
        self._started = False

    def register_handler(self, job_type: str, handler: Callable[[Job], None]) -> None:
        if job_type not in JOB_TYPES:
            raise ValueError(f"Unknown job type {job_type!r}")
        self._handlers[job_type] = handler

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self._ingest_workers):
            thread = threading.Thread(
                target=self._worker, args=(self._ingest_q,),
                name=f"ingest-worker-{i}", daemon=True,
            )
            thread.start()
            self._threads.append(thread)
        linker = threading.Thread(
            target=self._worker, args=(self._linker_q,),
            name="linker-worker", daemon=True,
        )
        linker.start()
        self._threads.append(linker)
        logger.info("Job queue started (%d ingest workers + 1 linker lane)",
                    self._ingest_workers)

    def stop(self, timeout: float = 30.0) -> None:
        """Signal workers and wait for the in-flight job to finish.

        Link runs are not atomic (nodes, edges, stale-sweep and GC are separate
        transactions), so killing one mid-flight leaves partial Layer-1/2 state.
        """
        if not self._started:
            return
        for _ in range(self._ingest_workers):
            self._ingest_q.put(_SENTINEL)
        self._linker_q.put(_SENTINEL)
        self._started = False
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        stragglers = [t.name for t in self._threads if t.is_alive()]
        if stragglers:
            logger.warning("Job workers still running at shutdown: %s",
                           ", ".join(stragglers))
        self._threads.clear()

    def submit(self, job_type: str, repo_id: str, payload: Optional[dict] = None,
               job_id: Optional[str] = None) -> str:
        """Enqueue a job; identical pending (type, repo) submissions coalesce."""
        if job_type not in JOB_TYPES:
            raise ValueError(f"Unknown job type {job_type!r}")
        key = (job_type, repo_id)
        with self._pending_lock:
            existing = self._pending.get(key)
            if existing:
                logger.info("Deduplicated %s for %s -> job %s", job_type, repo_id, existing)
                return existing
            new_id = job_id or str(uuid.uuid4())
            self._pending[key] = new_id

        job = Job(id=new_id, type=job_type, repo_id=repo_id, payload=payload or {})
        create_or_update_job(new_id, repo_id, "queued", 0, f"{job_type} queued")
        lane = self._ingest_q if job_type in INGEST_LANE else self._linker_q
        lane.put(job)
        return new_id

    def repo_lock(self, repo_id: str) -> threading.Lock:
        with self._repo_locks_guard:
            if repo_id not in self._repo_locks:
                self._repo_locks[repo_id] = threading.Lock()
            return self._repo_locks[repo_id]

    def _worker(self, lane: queue.Queue) -> None:
        while True:
            job = lane.get()
            if job is _SENTINEL:
                return
            with self._pending_lock:
                self._pending.pop((job.type, job.repo_id), None)
            handler = self._handlers.get(job.type)
            if handler is None:
                create_or_update_job(job.id, job.repo_id, "failed", 0,
                                     "No handler registered", f"unhandled type {job.type}")
                continue
            try:
                if job.type in EXCLUSIVE_JOBS:
                    with self._graph_lock.exclusive():
                        handler(job)
                else:
                    with self._graph_lock.shared(), self.repo_lock(job.repo_id):
                        handler(job)
            except Exception as exc:
                logger.exception("Job %s (%s) crashed", job.id, job.type)
                create_or_update_job(job.id, job.repo_id, "failed", 0,
                                     f"{job.type} crashed", str(exc)[:500])


def reap_stale_jobs() -> int:
    """Mark queued/running jobs orphaned by a restart as failed (in-process queue)."""
    from evigraph.db.neo4j_client import get_session
    with get_session() as session:
        result = session.run(
            "MATCH (j:IngestionJob) WHERE j.status IN ['queued', 'running'] "
            "SET j.status = 'failed', j.error = 'orphaned by backend restart', "
            "j.updated_at = datetime() RETURN count(j) AS c"
        )
        count = result.single()["c"]
    if count:
        logger.warning("Reaped %d stale jobs from a previous process", count)
    return count


job_queue = JobQueue()
