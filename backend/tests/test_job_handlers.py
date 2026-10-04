"""Job handlers schedule follow-up work only after successful mutations."""

from unittest.mock import MagicMock, patch

import pytest

from tracekite.services import job_handlers
from tracekite.services.job_queue import Job


def test_register_all():
    queue = MagicMock()
    job_handlers.register_all(queue)
    registered = {call.args[0] for call in queue.register_handler.call_args_list}
    assert registered == {"ingest", "refresh", "ingest_upload", "repo_delete",
                          "link_full", "link_delta"}


def test_handle_ingest_upload():
    job = Job(id="j1", type="ingest_upload", repo_id="local_demo",
              payload={"name": "demo", "bundle_path": "/tmp/x.bundle",
                       "branch": None})
    with patch("tracekite.services.job_handlers.run_upload_ingestion") as run, \
            patch("tracekite.services.job_handlers.discard_bundle") as discard, \
            patch("tracekite.services.job_handlers._enqueue_relink"):
        job_handlers._handle_ingest_upload(job)
    run.assert_called_once_with("j1", "local_demo", "demo", "/tmp/x.bundle",
                                branch=None)
    discard.assert_called_once_with("/tmp/x.bundle")


def test_failed_upload_is_discarded_without_relink():
    job = Job(id="j1", type="ingest_upload", repo_id="local_demo",
              payload={"name": "demo", "bundle_path": "/tmp/x.bundle"})
    with patch("tracekite.services.job_handlers.run_upload_ingestion",
               return_value=False), \
            patch("tracekite.services.job_handlers.discard_bundle") as discard, \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        job_handlers._handle_ingest_upload(job)
    discard.assert_called_once_with("/tmp/x.bundle")
    relink.assert_not_called()


def test_handle_ingest():
    job = Job(id="j1", type="ingest", repo_id="r1",
              payload={"github_url": "https://github.com/foo/bar",
                       "branch": "main", "github_token": "t", "refresh": False})
    with patch("tracekite.services.job_handlers.run_ingestion") as run, \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        job_handlers._handle_ingest(job)
    run.assert_called_once()
    assert run.call_args[0][0] == "j1"
    assert run.call_args[1]["refresh"] is False
    relink.assert_called_once()


def test_handle_refresh():
    job = Job(id="j2", type="refresh", repo_id="r1",
              payload={"github_url": "https://github.com/foo/bar"})
    with patch("tracekite.services.job_handlers.run_ingestion") as run, \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        job_handlers._handle_refresh(job)
    assert run.call_args[1]["refresh"] is True
    relink.assert_called_once()


def test_raised_ingest_failure_does_not_relink():
    job = Job(id="j3", type="ingest", repo_id="r1",
              payload={"github_url": "https://github.com/foo/bar"})
    with patch("tracekite.services.job_handlers.run_ingestion",
               side_effect=RuntimeError("clone failed")), \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        with pytest.raises(RuntimeError):
            job_handlers._handle_ingest(job)
    relink.assert_not_called()


def test_cleanly_reported_failure_does_not_relink():
    job = Job(id="j3", type="ingest", repo_id="r1",
              payload={"github_url": "https://github.com/foo/bar"})
    with patch("tracekite.services.job_handlers.run_ingestion", return_value=False), \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        job_handlers._handle_ingest(job)
    relink.assert_not_called()


def test_repo_delete_relinks_when_claims_existed():
    job = Job(id="j4", type="repo_delete", repo_id="r1")
    with patch("tracekite.services.job_handlers.create_or_update_job"), \
            patch("tracekite.services.job_handlers.get_repo_claim_keys",
                  return_value=["svcname:discovery:orders"]), \
            patch("tracekite.services.job_handlers.clear_repo_graph",
                  return_value={"nodes_deleted": 5}), \
            patch("tracekite.services.job_handlers.delete_repository"), \
            patch("tracekite.services.job_handlers._enqueue_relink") as relink:
        job_handlers._handle_repo_delete(job)
    relink.assert_called_once()


def test_handle_link_full():
    job = Job(id="j3", type="link_full", repo_id="r1", payload={})
    fake_service = MagicMock()
    fake_service.return_value.link_full.return_value = {"edges_written": 7}
    with patch("tracekite.services.linker.LinkerService", fake_service), \
         patch("tracekite.services.job_handlers.create_or_update_job") as update:
        job_handlers._handle_link_full(job)
    assert update.call_args_list[0].args[2] == "running"
    assert update.call_args_list[-1].args[2] == "completed"
    assert "7 edges" in update.call_args_list[-1].args[4]


def test_handle_link_full_exception_propagates():
    job = Job(id="j3", type="link_full", repo_id="r1", payload={})
    fake_service = MagicMock()
    fake_service.return_value.link_full.side_effect = RuntimeError("boom")
    with patch("tracekite.services.linker.LinkerService", fake_service), \
         patch("tracekite.services.job_handlers.create_or_update_job"):
        with pytest.raises(RuntimeError, match="boom"):
            job_handlers._handle_link_full(job)


def test_handle_repo_delete():
    job = Job(id="j4", type="repo_delete", repo_id="r1", payload={})
    with patch("tracekite.services.job_handlers.get_repo_claim_keys",
               return_value=["k1", "k2"]), \
         patch("tracekite.services.job_handlers.clear_repo_graph",
               return_value={"nodes_deleted": 5}), \
         patch("tracekite.services.job_handlers.delete_repository") as delete, \
         patch("tracekite.services.job_handlers._enqueue_relink"), \
         patch("tracekite.services.job_handlers.create_or_update_job") as update:
        job_handlers._handle_repo_delete(job)
    delete.assert_called_once_with("r1")
    assert update.call_args_list[-1].args[2] == "completed"
    assert "5 nodes" in update.call_args_list[-1].args[4]


def test_handle_repo_delete_no_claim_keys():
    job = Job(id="j5", type="repo_delete", repo_id="r1", payload={})
    with patch("tracekite.services.job_handlers.get_repo_claim_keys",
               return_value=[]), \
         patch("tracekite.services.job_handlers.clear_repo_graph",
               return_value={"nodes_deleted": 0}), \
         patch("tracekite.services.job_handlers.delete_repository"), \
         patch("tracekite.services.job_handlers.create_or_update_job"):
        job_handlers._handle_repo_delete(job)
