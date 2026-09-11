"""Coverage for the linker write path, execution service, job handlers, queue."""

import threading
from unittest.mock import MagicMock, patch

import pytest

from evigraph.models.graph_models import GraphEdge
from evigraph.services import graph_writer, link_writer
from evigraph.services.linker import engine as linker_engine
from evigraph.services.linker import service as linker_service
from evigraph.services.linker.base import RendezvousSpec, ServiceSpec
from evigraph.services.linker_store import Neo4jLinkerStore


# --------------------------------------------------------------------------- #
# Fake Neo4j session helpers                                                   #
# --------------------------------------------------------------------------- #

class FakeResult:
    def __init__(self, single_value=None, records=None, consume_obj=None):
        self._single = single_value
        self._records = records or []
        self._consume = consume_obj or MagicMock()

    def single(self):
        return self._single

    def __iter__(self):
        return iter(self._records)

    def consume(self):
        return self._consume


class FakeSession:
    """Captures every (query, params) pair; returns queued FakeResults."""

    def __init__(self, results=None):
        self.calls = []
        self._results = list(results or [])

    def run(self, query, **params):
        self.calls.append((query, params))
        if self._results:
            return self._results.pop(0)
        return FakeResult()


def _ctx(session):
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False
    return ctx


# --------------------------------------------------------------------------- #
# link_writer.py                                                               #
# --------------------------------------------------------------------------- #

class TestWriteRendezvousNodes:
    def test_happy_path_per_label(self):
        specs = [
            RendezvousSpec("ServiceName", "svc:a", {"repo_ids": ["r1"]}),
            RendezvousSpec("Topic", "topic:b", {"repo_ids": ["r2"]}),
        ]
        session = FakeSession([
            FakeResult(single_value={"c": 1}),
            FakeResult(single_value={"c": 1}),
        ])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            total = link_writer.write_rendezvous_nodes(specs)
        assert total == 2
        assert len(session.calls) == 2
        query, params = session.calls[0]
        assert "MERGE (n:ServiceName:Rendezvous" in query
        assert params["rows"] == [{"id": "svc:a", "props": {"repo_ids": ["r1"]}}]
        assert "now" in params

    def test_rejects_non_rendezvous_label(self):
        specs = [RendezvousSpec("NotALabel", "x", {})]
        with pytest.raises(ValueError, match="not a rendezvous label"):
            link_writer.write_rendezvous_nodes(specs)


class TestWriteServiceNodes:
    def test_no_gateway(self):
        specs = [ServiceSpec("global:Service:a", "a", is_gateway=False,
                             repo_ids=["r1"])]
        session = FakeSession([FakeResult(single_value={"c": 1})])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            total = link_writer.write_service_nodes(specs)
        assert total == 1
        assert len(session.calls) == 1
        query, params = session.calls[0]
        assert "MERGE (n:Service {id: row.id})" in query
        assert params["rows"] == [{"id": "global:Service:a", "name": "a",
                                   "repo_ids": ["r1"]}]

    def test_gateway_branch(self):
        specs = [ServiceSpec("global:Service:gw", "gw", is_gateway=True,
                             repo_ids=["r1"])]
        session = FakeSession([FakeResult(single_value={"c": 1})])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            total = link_writer.write_service_nodes(specs)
        assert total == 1
        assert len(session.calls) == 2
        gw_query, gw_params = session.calls[1]
        assert "SET n:Gateway" in gw_query
        assert gw_params["ids"] == ["global:Service:gw"]


class TestLinkRunLedger:
    def test_create_link_run(self):
        session = FakeSession()
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.create_link_run("run1", "full")
        query, params = session.calls[0]
        assert "MERGE (l:LinkRun {id: $id})" in query
        assert params["id"] == "run1"
        assert params["mode"] == "full"

    def test_finish_link_run_with_error(self):
        session = FakeSession()
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.finish_link_run("run1", "failed", {"a": 1}, error="boom")
        query, params = session.calls[0]
        assert "SET l.status = $status" in query
        assert params["status"] == "failed"
        assert params["error"] == "boom"
        assert params["counters"] == '{"a": 1}'

    def test_finish_link_run_default_error(self):
        session = FakeSession()
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.finish_link_run("run1", "done", {"x": 2})
        _, params = session.calls[0]
        assert params["status"] == "done"
        assert params["error"] == ""
        assert params["counters"] == '{"x": 2}'

    def test_list_link_runs_round_trip(self):
        records = [
            {"props": {"id": "r1", "counters": '{"edges": 3}'}},
            {"props": {"id": "r2", "counters": None}},
            {"props": {"id": "r3", "counters": "not-json"}},
        ]
        session = FakeSession([FakeResult(records=records)])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            runs = link_writer.list_link_runs(limit=5)
        assert runs[0]["counters"] == {"edges": 3}
        assert runs[1]["counters"] == {}
        assert runs[2]["counters"] == {}
        _, params = session.calls[0]
        assert params["limit"] == 5

    def test_list_link_runs_empty(self):
        session = FakeSession([FakeResult(records=[])])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            runs = link_writer.list_link_runs()
        assert runs == []


class TestDeleteStaleLinkerEdges:
    def test_returns_deleted_count_and_logs(self):
        consume = MagicMock()
        consume.counters.relationships_deleted = 4
        session = FakeSession([FakeResult(consume_obj=consume)])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            deleted = link_writer.delete_stale_linker_edges("run1")
        assert deleted == 4
        query, params = session.calls[0]
        assert "CALL { WITH r DELETE r } IN TRANSACTIONS" in query
        assert params["run"] == "run1"

    def test_zero_deleted_skips_log(self):
        consume = MagicMock()
        consume.counters.relationships_deleted = 0
        session = FakeSession([FakeResult(consume_obj=consume)])
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            deleted = link_writer.delete_stale_linker_edges("run1")
        assert deleted == 0


class TestStampReposLinked:
    def test_empty_repo_ids_returns_early(self):
        session = FakeSession()
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.stamp_repos_linked([], "run1")
        assert session.calls == []

    def test_stamps_repos(self):
        session = FakeSession()
        with patch("evigraph.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.stamp_repos_linked(["r1", "r2"], "run1")
        query, params = session.calls[0]
        assert "SET r.linked_at = $now" in query
        assert params["ids"] == ["r1", "r2"]
        assert params["run"] == "run1"


# --------------------------------------------------------------------------- #
# linker/service.py                                                            #
# --------------------------------------------------------------------------- #

class TestLoadClaims:
    def test_load_claims_shapes_records(self):
        records = [
            {"props": {"id": "c1", "repo_id": "r1", "kind": "svcname",
                       "direction": "provides", "key": "k", "matchable": True,
                       "evidence": ["a.yml:1"], "metadata": '{"src": "x"}'},
             "enode": "n1", "etype": "GraphNode"},
            {"props": {"id": "c2", "repo_id": "r2", "metadata": "bad-json"},
             "enode": None, "etype": None},
        ]
        session = FakeSession([FakeResult(records=records)])
        with patch("evigraph.services.linker_store.get_session",
                   return_value=_ctx(session)):
            claims = Neo4jLinkerStore().load_claims()
        assert len(claims) == 2
        assert claims[0].id == "c1"
        assert claims[0].attrs == {"src": "x"}
        assert claims[0].evidence_node_id == "n1"
        assert claims[1].attrs == {}
        assert claims[1].evidence_node_type == ""

    def test_load_claims_only_reads_linkable_repos(self):
        """A failed_partial repo's claims must never reach a resolver: its
        evidence nodes are incomplete, so edges built off them look resolved
        and are silently wrong."""
        session = FakeSession([FakeResult(records=[])])
        with patch("evigraph.services.linker_store.get_session",
                   return_value=_ctx(session)):
            Neo4jLinkerStore().load_claims()
        _query, params = session.calls[0]
        assert params["states"] == ["ingested", "linking", "linked"]


class FakeLinkerStore:
    """A LinkerStore held in memory, so a link run needs no database.

    Replaces a twelve-patch tower: the linker now takes its storage as an
    argument, so a test supplies one object instead of reaching into the
    module to rewrite each collaborator in place.
    """

    def __init__(self, claims=None, fingerprints=None, stored=None,
                 unlinkable=None):
        self.claims = list(claims or [])
        self.fingerprints = dict(fingerprints or {})
        self.stored = dict(stored or {})
        self.unlinkable = dict(unlinkable or {})
        self.stored_written = None
        self.created = []
        self.finished = None
        self.stamped = []
        self.written_edges = None
        self.fail_on_rendezvous = None

    def load_claims(self):
        return self.claims

    def unlinkable_repos(self):
        return self.unlinkable

    def claim_fingerprints(self):
        return self.fingerprints

    def stored_fingerprints(self):
        return self.stored

    def store_fingerprints(self, fingerprints):
        self.stored_written = dict(fingerprints)

    def create_link_run(self, run_id, mode):
        self.created.append((run_id, mode))

    def finish_link_run(self, run_id, status, counters, error=None):
        self.finished = {"run_id": run_id, "status": status,
                         "counters": counters, "error": error}

    def write_rendezvous_nodes(self, specs):
        if self.fail_on_rendezvous is not None:
            raise self.fail_on_rendezvous
        return len(specs)

    def write_service_nodes(self, specs):
        return len(specs)

    def write_linker_edges(self, edges):
        self.written_edges = list(edges)
        return {"CALLS_SERVICE": 3}

    def delete_stale_linker_edges(self, current_run_id):
        return 2

    def stamp_repos_linked(self, repo_ids, run_id):
        self.stamped.append((tuple(repo_ids), run_id))

    def gc_orphan_rendezvous(self):
        return 1


class TestLinkerServiceLinkFull:
    def _patches(self):
        """Only the config loaders remain patched — they read YAML off disk,
        which is not storage the linker's port covers."""
        return (
            patch("evigraph.services.linker.engine.load_confidence",
                  return_value={}),
            patch("evigraph.services.linker.engine.load_aliases", return_value={}),
            patch("evigraph.services.linker.engine.build_rollups", return_value=[]),
        )

    def test_link_full_success(self):
        from evigraph.services.linker.base import ClaimRecord
        claim = ClaimRecord(
            id="c1", repo_id="r1", kind="svcname", direction="provides",
            key="k", service_hint=None, hint_source="none", matchable=True,
            evidence=["a.yml:1"], attrs={}, evidence_node_id=None,
            evidence_node_type="",
        )
        store = FakeLinkerStore(claims=[claim])
        conf, aliases, rollups = self._patches()
        with conf, aliases, rollups:
            result = linker_service.LinkerService(store).link_full()

        assert result["link_run_id"].startswith("linkrun_")
        assert result["edges_written"] == 3
        assert result["edges_by_type"] == {"CALLS_SERVICE": 3}
        assert result["stale_edges_deleted"] == 2
        assert result["orphans_gcd"] == 1
        assert result["claims_loaded"] == 1
        assert len(store.created) == 1
        assert len(store.stamped) == 1
        assert store.finished["status"] == "done"

    def test_link_full_empty_claims(self):
        store = FakeLinkerStore(claims=[])
        conf, aliases, rollups = self._patches()
        with conf, aliases, rollups:
            result = linker_service.LinkerService(store).link_full()
        assert result["claims_loaded"] == 0
        assert store.finished["status"] == "done"

    def test_link_full_failure_propagates(self):
        store = FakeLinkerStore(claims=[])
        store.fail_on_rendezvous = RuntimeError("kaboom")
        conf, aliases, rollups = self._patches()
        with conf, aliases, rollups:
            with pytest.raises(RuntimeError, match="kaboom"):
                linker_service.LinkerService(store).link_full()
        assert store.finished["status"] == "failed"
        assert "kaboom" in store.finished["error"]

    def test_link_delta_skips_when_no_claims_changed(self):
        """The fingerprint gate is the whole point of delta: an unchanged
        estate must not pay for a full relink."""
        store = FakeLinkerStore(fingerprints={"r1": "abc"},
                                stored={"r1": "abc"})
        result = linker_service.LinkerService(store).link_delta()
        assert result["skipped"] is True
        assert result["repos_changed"] == 0
        assert store.created == []

    def test_link_delta_relinks_and_restamps_when_changed(self):
        store = FakeLinkerStore(fingerprints={"r1": "new"},
                                stored={"r1": "old"})
        conf, aliases, rollups = self._patches()
        with conf, aliases, rollups:
            result = linker_service.LinkerService(store).link_delta()
        assert result["repos_changed"] == 1
        assert store.stored_written == {"r1": "new"}


class TestDedupe:
    def test_dedupe_rendezvous_merges_repo_ids(self):
        combined = MagicMock()
        combined.rendezvous = [
            RendezvousSpec("ServiceName", "svc:a", {"repo_ids": ["r1"]}),
            RendezvousSpec("ServiceName", "svc:a", {"repo_ids": ["r2"]}),
            RendezvousSpec("Topic", "t:b", {"repo_ids": ["r3"]}),
        ]
        merged = linker_engine.dedupe_rendezvous(combined)
        assert len(merged) == 2
        svc = next(s for s in merged if s.node_id == "svc:a")
        assert svc.props["repo_ids"] == ["r1", "r2"]

    def test_dedupe_services_merges(self):
        combined = MagicMock()
        combined.services = [
            ServiceSpec("s1", "a", is_gateway=False, repo_ids=["r1"]),
            ServiceSpec("s1", "a", is_gateway=True, repo_ids=["r2"]),
            ServiceSpec("s2", "b", is_gateway=False, repo_ids=["r3"]),
        ]
        merged = linker_engine.dedupe_services(combined)
        assert len(merged) == 2
        s1 = next(s for s in merged if s.service_id == "s1")
        assert s1.is_gateway is True
        assert s1.repo_ids == ["r1", "r2"]


# --------------------------------------------------------------------------- #
# job_handlers.py                                                              #
# --------------------------------------------------------------------------- #

class TestJobHandlers:
    def test_register_all(self):
        from evigraph.services import job_handlers
        queue = MagicMock()
        job_handlers.register_all(queue)
        registered = {c.args[0] for c in queue.register_handler.call_args_list}
        assert registered == {"ingest", "refresh", "repo_delete", "link_full",
                              "link_delta"}

    def test_handle_ingest(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j1", type="ingest", repo_id="r1",
                  payload={"github_url": "https://github.com/foo/bar",
                           "branch": "main", "github_token": "t", "refresh": False})
        with patch("evigraph.services.job_handlers.run_ingestion") as run, \
                patch("evigraph.services.job_handlers._enqueue_relink") as relink:
            job_handlers._handle_ingest(job)
        run.assert_called_once()
        assert run.call_args[0][0] == "j1"
        assert run.call_args[1]["refresh"] is False
        # Layer-1/2 is a cache of Layer-0: a completed ingest must schedule a
        # relink or the graph keeps serving pre-ingest answers.
        relink.assert_called_once()

    def test_handle_refresh(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j2", type="refresh", repo_id="r1",
                  payload={"github_url": "https://github.com/foo/bar"})
        with patch("evigraph.services.job_handlers.run_ingestion") as run, \
                patch("evigraph.services.job_handlers._enqueue_relink") as relink:
            job_handlers._handle_refresh(job)
        assert run.call_args[1]["refresh"] is True
        relink.assert_called_once()

    def test_failed_ingest_does_not_relink(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j3", type="ingest", repo_id="r1",
                  payload={"github_url": "https://github.com/foo/bar"})
        with patch("evigraph.services.job_handlers.run_ingestion",
                   side_effect=RuntimeError("clone failed")), \
                patch("evigraph.services.job_handlers._enqueue_relink") as relink:
            with pytest.raises(RuntimeError):
                job_handlers._handle_ingest(job)
        relink.assert_not_called()

    def test_repo_delete_relinks_when_claims_existed(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j4", type="repo_delete", repo_id="r1")
        with patch("evigraph.services.job_handlers.create_or_update_job"), \
                patch("evigraph.services.job_handlers.get_repo_claim_keys",
                      return_value=["svcname:discovery:orders"]), \
                patch("evigraph.services.job_handlers.clear_repo_graph",
                      return_value={"nodes_deleted": 5}), \
                patch("evigraph.services.job_handlers.delete_repository"), \
                patch("evigraph.services.job_handlers._enqueue_relink") as relink:
            job_handlers._handle_repo_delete(job)
        # Service-to-Service rollups outlive the deleted repo's nodes.
        relink.assert_called_once()

    def test_handle_link_full(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j3", type="link_full", repo_id="r1", payload={})
        fake_service = MagicMock()
        fake_service.return_value.link_full.return_value = {"edges_written": 7}
        with patch("evigraph.services.linker.LinkerService", fake_service), \
             patch("evigraph.services.job_handlers.create_or_update_job") as cj:
            job_handlers._handle_link_full(job)
        assert cj.call_args_list[0].args[2] == "running"
        assert cj.call_args_list[-1].args[2] == "completed"
        assert "7 edges" in cj.call_args_list[-1].args[4]

    def test_handle_link_full_exception_propagates(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j3", type="link_full", repo_id="r1", payload={})
        fake_service = MagicMock()
        fake_service.return_value.link_full.side_effect = RuntimeError("boom")
        with patch("evigraph.services.linker.LinkerService", fake_service), \
             patch("evigraph.services.job_handlers.create_or_update_job"):
            with pytest.raises(RuntimeError, match="boom"):
                job_handlers._handle_link_full(job)

    def test_handle_repo_delete(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j4", type="repo_delete", repo_id="r1", payload={})
        with patch("evigraph.services.job_handlers.get_repo_claim_keys",
                   return_value=["k1", "k2"]), \
             patch("evigraph.services.job_handlers.clear_repo_graph",
                   return_value={"nodes_deleted": 5}), \
             patch("evigraph.services.job_handlers.delete_repository") as delete, \
             patch("evigraph.services.job_handlers._enqueue_relink"), \
             patch("evigraph.services.job_handlers.create_or_update_job") as cj:
            job_handlers._handle_repo_delete(job)
        delete.assert_called_once_with("r1")
        assert cj.call_args_list[-1].args[2] == "completed"
        assert "5 nodes" in cj.call_args_list[-1].args[4]

    def test_handle_repo_delete_no_claim_keys(self):
        from evigraph.services import job_handlers
        from evigraph.services.job_queue import Job
        job = Job(id="j5", type="repo_delete", repo_id="r1", payload={})
        with patch("evigraph.services.job_handlers.get_repo_claim_keys",
                   return_value=[]), \
             patch("evigraph.services.job_handlers.clear_repo_graph",
                   return_value={"nodes_deleted": 0}), \
             patch("evigraph.services.job_handlers.delete_repository"), \
             patch("evigraph.services.job_handlers.create_or_update_job"):
            job_handlers._handle_repo_delete(job)


# --------------------------------------------------------------------------- #
# job_queue.py                                                                 #
# --------------------------------------------------------------------------- #

class TestJobQueue:
    def test_register_handler_rejects_unknown(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue()
        with pytest.raises(ValueError, match="Unknown job type"):
            q.register_handler("bogus", lambda job: None)

    def test_submit_rejects_unknown(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue()
        with pytest.raises(ValueError, match="Unknown job type"):
            q.submit("bogus", "r1")

    def test_submit_and_dedupe(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue()
        with patch("evigraph.services.job_queue.create_or_update_job") as cj:
            first = q.submit("ingest", "r1", job_id="fixed")
            second = q.submit("ingest", "r1")
        assert first == "fixed"
        assert second == "fixed"  # deduped
        assert cj.call_count == 1
        # ingest lane got the job
        assert q._ingest_q.qsize() == 1

    def test_submit_linker_lane(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue()
        with patch("evigraph.services.job_queue.create_or_update_job"):
            q.submit("link_full", "r1", payload={"x": 1})
        assert q._linker_q.qsize() == 1
        assert q._ingest_q.qsize() == 0

    def test_repo_lock_reuses_lock(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue()
        lock1 = q.repo_lock("r1")
        lock2 = q.repo_lock("r1")
        assert lock1 is lock2

    def test_worker_executes_handler(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue(ingest_workers=1)
        done = threading.Event()

        def handler(job):
            done.set()

        with patch("evigraph.services.job_queue.create_or_update_job"):
            q.register_handler("ingest", handler)
            q.start()
            # idempotent second start
            q.start()
            q.submit("ingest", "r1")
            assert done.wait(timeout=2.0)
            q.stop()
            # idempotent second stop
            q.stop()
        for t in q._threads:
            t.join(timeout=2.0)
            assert not t.is_alive()

    def test_worker_no_handler_marks_failed(self):
        from evigraph.services.job_queue import JobQueue, Job
        q = JobQueue()
        failed = threading.Event()

        def fake_create(job_id, repo_id, status, *args, **kwargs):
            if status == "failed":
                failed.set()

        with patch("evigraph.services.job_queue.create_or_update_job",
                   side_effect=fake_create):
            # put a job whose type has no registered handler
            q._linker_q.put(Job(id="j", type="link_full", repo_id="r1"))
            t = threading.Thread(target=q._worker, args=(q._linker_q,),
                                 daemon=True)
            t.start()
            assert failed.wait(timeout=2.0)
            q._linker_q.put(None)  # sentinel to stop
            t.join(timeout=2.0)
        assert not t.is_alive()

    def test_worker_handler_exception_marks_failed(self):
        from evigraph.services.job_queue import JobQueue
        q = JobQueue(ingest_workers=1)
        failed = threading.Event()

        def fake_create(job_id, repo_id, status, *args, **kwargs):
            if status == "failed":
                failed.set()

        def boom(job):
            raise RuntimeError("crash")

        with patch("evigraph.services.job_queue.create_or_update_job",
                   side_effect=fake_create):
            q.register_handler("ingest", boom)
            q.start()
            q.submit("ingest", "r1")
            assert failed.wait(timeout=2.0)
            q.stop()
        for t in q._threads:
            t.join(timeout=2.0)

    def test_reap_stale_jobs(self):
        from evigraph.services import job_queue
        session = FakeSession([FakeResult(single_value={"c": 3})])
        with patch("evigraph.db.neo4j_client.get_session", return_value=_ctx(session)):
            count = job_queue.reap_stale_jobs()
        assert count == 3

    def test_reap_stale_jobs_zero(self):
        from evigraph.services import job_queue
        session = FakeSession([FakeResult(single_value={"c": 0})])
        with patch("evigraph.db.neo4j_client.get_session", return_value=_ctx(session)):
            count = job_queue.reap_stale_jobs()
        assert count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# --------------------------------------------------------------------------- #
# graph_writer.write_linker_edges                                              #
# --------------------------------------------------------------------------- #

def _linker_edge(edge_type="BUILT_FROM", source="s1", target="t1", **over):
    edge = GraphEdge(
        source_id=source, target_id=target, repo_id="r1", type=edge_type,
        confidence=0.9, origin="matched", detected_by="resolver.image@1",
        created_by="linker", link_run_id="linkrun_x",
    )
    for key, value in over.items():
        setattr(edge, key, value)
    return edge


class TestWriteLinkerEdges:
    def test_groups_by_type_and_labels_and_reconciles(self):
        edges = [
            _linker_edge(),
            _linker_edge(source="s2", target="t2"),
            _linker_edge("EXPOSES", source="svc", target="c1",
                         source_label="Service", target_label="HttpContract"),
        ]
        session = FakeSession([
            FakeResult(single_value={"c": 2}),
            FakeResult(single_value={"c": 1}),
        ])
        with patch("evigraph.services.graph_writer.get_session",
                   return_value=_ctx(session)):
            written = graph_writer.write_linker_edges(edges)
        assert written == {"BUILT_FROM": 2, "EXPOSES": 1}
        q1, p1 = session.calls[0]
        assert "MERGE (a)-[r:BUILT_FROM {detected_by: row.detected_by}]" in q1
        assert "MATCH (a:GraphNode" in q1
        assert {row["source"] for row in p1["rows"]} == {"s1", "s2"}
        q2, _ = session.calls[1]
        assert "MATCH (a:Service" in q2
        assert "MATCH (b:HttpContract" in q2

    def test_rejects_non_linker_edge_type(self):
        with pytest.raises(ValueError, match="not a linker edge type"):
            graph_writer.write_linker_edges([_linker_edge("CONTAINS")])

    def test_rejects_missing_provenance(self):
        bad = _linker_edge()
        bad.created_by = "ingestion"
        with pytest.raises(ValueError, match="missing provenance"):
            graph_writer.write_linker_edges([bad])
        bad2 = _linker_edge()
        bad2.detected_by = ""
        with pytest.raises(ValueError, match="missing provenance"):
            graph_writer.write_linker_edges([bad2])

    def test_reconciliation_mismatch_raises(self):
        edges = [_linker_edge(), _linker_edge(source="s2", target="t2")]
        session = FakeSession([FakeResult(single_value={"c": 1})])
        with patch("evigraph.services.graph_writer.get_session",
                   return_value=_ctx(session)), \
             patch("evigraph.services.graph_writer._diagnose_missing",
                   return_value=["s1->t1"]):
            with pytest.raises(graph_writer.WriteReconciliationError):
                graph_writer.write_linker_edges(edges)


class TestPartialFailureReporting:
    """A repo excluded from the link is named and counted.

    Skipping a `failed_partial` repo is correct — its evidence is incomplete,
    so edges built off it would look resolved and be silently wrong. Skipping
    it *quietly* is what makes an estate with a broken repo indistinguishable
    from a smaller estate, and turns missing edges into an apparent recall
    problem rather than an operational one.
    """

    def _run(self, store):
        conf = patch("evigraph.services.linker.engine.load_confidence",
                     return_value={})
        aliases = patch("evigraph.services.linker.engine.load_aliases",
                        return_value={})
        rollups = patch("evigraph.services.linker.engine.build_rollups",
                        return_value=[])
        with conf, aliases, rollups:
            return linker_service.LinkerService(store).link_full()

    def test_healthy_estate_reports_zero_excluded(self):
        counters = self._run(FakeLinkerStore(claims=[]))
        assert counters["repos_excluded"] == 0
        assert counters["repos_excluded_detail"] == {}

    def test_excluded_repo_is_named_with_its_state(self):
        store = FakeLinkerStore(
            claims=[], unlinkable={"repo-b": "failed_partial"})
        counters = self._run(store)
        assert counters["repos_excluded"] == 1
        assert counters["repos_excluded_detail"] == {
            "repo-b": "failed_partial"}

    def test_counters_reach_the_link_run_ledger(self):
        """The count must survive into the stored run, or an operator reading
        history cannot tell which runs were partial."""
        store = FakeLinkerStore(
            claims=[], unlinkable={"repo-c": "failed_clean"})
        self._run(store)
        assert store.finished["counters"]["repos_excluded"] == 1
