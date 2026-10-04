"""Coverage for the linker write path, execution service, job handlers, queue."""

from unittest.mock import MagicMock, patch

import pytest

from tracekite.models.graph_models import GraphEdge
from tracekite.services import graph_writer, link_writer
from tracekite.services.linker import engine as linker_engine
from tracekite.services.linker import service as linker_service
from tracekite.services.linker.base import RendezvousSpec, ServiceSpec
from tracekite.services.linker_store import Neo4jLinkerStore


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
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
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
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
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
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            total = link_writer.write_service_nodes(specs)
        assert total == 1
        assert len(session.calls) == 2
        gw_query, gw_params = session.calls[1]
        assert "SET n:Gateway" in gw_query
        assert gw_params["ids"] == ["global:Service:gw"]


class TestLinkRunLedger:
    def test_create_link_run(self):
        session = FakeSession()
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.create_link_run("run1", "full")
        query, params = session.calls[0]
        assert "MERGE (l:LinkRun {id: $id})" in query
        assert params["id"] == "run1"
        assert params["mode"] == "full"

    def test_finish_link_run_with_error(self):
        session = FakeSession()
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.finish_link_run("run1", "failed", {"a": 1}, error="boom")
        query, params = session.calls[0]
        assert "SET l.status = $status" in query
        assert params["status"] == "failed"
        assert params["error"] == "boom"
        assert params["counters"] == '{"a": 1}'

    def test_finish_link_run_default_error(self):
        session = FakeSession()
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
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
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            runs = link_writer.list_link_runs(limit=5)
        assert runs[0]["counters"] == {"edges": 3}
        assert runs[1]["counters"] == {}
        assert runs[2]["counters"] == {}
        _, params = session.calls[0]
        assert params["limit"] == 5

    def test_list_link_runs_empty(self):
        session = FakeSession([FakeResult(records=[])])
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            runs = link_writer.list_link_runs()
        assert runs == []


class TestDeleteStaleLinkerEdges:
    def test_returns_deleted_count_and_logs(self):
        consume = MagicMock()
        consume.counters.relationships_deleted = 4
        session = FakeSession([FakeResult(consume_obj=consume)])
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            deleted = link_writer.delete_stale_linker_edges("run1")
        assert deleted == 4
        query, params = session.calls[0]
        assert "CALL { WITH r DELETE r } IN TRANSACTIONS" in query
        assert params["run"] == "run1"

    def test_zero_deleted_skips_log(self):
        consume = MagicMock()
        consume.counters.relationships_deleted = 0
        session = FakeSession([FakeResult(consume_obj=consume)])
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            deleted = link_writer.delete_stale_linker_edges("run1")
        assert deleted == 0


class TestStampReposLinked:
    def test_empty_repo_ids_returns_early(self):
        session = FakeSession()
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
            link_writer.stamp_repos_linked([], "run1")
        assert session.calls == []

    def test_stamps_repos(self):
        session = FakeSession()
        with patch("tracekite.services.link_writer.get_session", return_value=_ctx(session)):
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
        with patch("tracekite.services.linker_store.get_session",
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
        with patch("tracekite.services.linker_store.get_session",
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
            patch("tracekite.services.linker.engine.load_confidence",
                  return_value={}),
            patch("tracekite.services.linker.engine.load_aliases", return_value={}),
            patch("tracekite.services.linker.engine.build_rollups", return_value=[]),
        )

    def test_link_full_success(self):
        from tracekite.services.linker.base import ClaimRecord
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
        with patch("tracekite.services.graph_writer.get_session",
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
        with patch("tracekite.services.graph_writer.get_session",
                   return_value=_ctx(session)), \
             patch("tracekite.services.graph_writer._diagnose_missing",
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
        conf = patch("tracekite.services.linker.engine.load_confidence",
                     return_value={})
        aliases = patch("tracekite.services.linker.engine.load_aliases",
                        return_value={})
        rollups = patch("tracekite.services.linker.engine.build_rollups",
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
