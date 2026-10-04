"""The two-lane job queue serializes mutations and reports worker failure."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from tracekite.services import job_queue
from tracekite.services.job_queue import Job, JobQueue


class FakeResult:
    def __init__(self, count):
        self._row = {"c": count}

    def single(self):
        return self._row


def _session(count):
    session = MagicMock()
    session.run.return_value = FakeResult(count)
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = False
    return context


def test_register_handler_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown job type"):
        JobQueue().register_handler("bogus", lambda job: None)


def test_submit_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown job type"):
        JobQueue().submit("bogus", "r1")


def test_submit_and_dedupe():
    queue = JobQueue()
    with patch("tracekite.services.job_queue.create_or_update_job") as update:
        first = queue.submit("ingest", "r1", job_id="fixed")
        second = queue.submit("ingest", "r1")
    assert first == second == "fixed"
    assert update.call_count == 1
    assert queue._ingest_q.qsize() == 1


def test_submit_linker_lane():
    queue = JobQueue()
    with patch("tracekite.services.job_queue.create_or_update_job"):
        queue.submit("link_full", "r1", payload={"x": 1})
    assert queue._linker_q.qsize() == 1
    assert queue._ingest_q.qsize() == 0


def test_repo_lock_reuses_lock():
    queue = JobQueue()
    assert queue.repo_lock("r1") is queue.repo_lock("r1")


def test_worker_executes_handler():
    queue = JobQueue(ingest_workers=1)
    done = threading.Event()
    with patch("tracekite.services.job_queue.create_or_update_job"):
        queue.register_handler("ingest", lambda job: done.set())
        queue.start()
        queue.start()
        queue.submit("ingest", "r1")
        assert done.wait(timeout=2.0)
        queue.stop()
        queue.stop()
    for thread in queue._threads:
        thread.join(timeout=2.0)
        assert not thread.is_alive()
    assert queue._pending == {}


def test_running_link_job_coalesces_new_submissions():
    queue = JobQueue()
    started, release = threading.Event(), threading.Event()

    def handler(job):
        started.set()
        assert release.wait(timeout=2.0)

    with patch("tracekite.services.job_queue.create_or_update_job"):
        queue.register_handler("link_full", handler)
        queue.start()
        first = queue.submit("link_full", "__linker__", job_id="one-link")
        assert started.wait(timeout=2.0)
        second = queue.submit("link_full", "__linker__")
        assert second == first
        assert queue._linker_q.empty()
        release.set()
        queue.stop()
    for thread in queue._threads:
        thread.join(timeout=2.0)


def test_worker_no_handler_marks_failed():
    queue = JobQueue()
    failed = threading.Event()

    def fake_create(job_id, repo_id, status, *args, **kwargs):
        if status == "failed":
            failed.set()

    with patch("tracekite.services.job_queue.create_or_update_job",
               side_effect=fake_create):
        queue._linker_q.put(Job(id="j", type="link_full", repo_id="r1"))
        thread = threading.Thread(target=queue._worker, args=(queue._linker_q,),
                                  daemon=True)
        thread.start()
        assert failed.wait(timeout=2.0)
        queue._linker_q.put(None)
        thread.join(timeout=2.0)
    assert not thread.is_alive()


def test_worker_handler_exception_marks_failed():
    queue = JobQueue(ingest_workers=1)
    failed = threading.Event()

    def fake_create(job_id, repo_id, status, *args, **kwargs):
        if status == "failed":
            failed.set()

    def boom(job):
        raise RuntimeError("crash")

    with patch("tracekite.services.job_queue.create_or_update_job",
               side_effect=fake_create):
        queue.register_handler("ingest", boom)
        queue.start()
        queue.submit("ingest", "r1")
        assert failed.wait(timeout=2.0)
        queue.stop()
    for thread in queue._threads:
        thread.join(timeout=2.0)


@pytest.mark.parametrize(("count"), [3, 0])
def test_reap_stale_jobs(count):
    with patch("tracekite.db.neo4j_client.get_session",
               return_value=_session(count)):
        assert job_queue.reap_stale_jobs() == count
