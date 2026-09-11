"""N writers, no corruption, no lost edges.

Parallel MAP and parallel REDUCE are the whole of Phase 2's scale story, and
both end in concurrent writes to one store. Before this, `SQLiteGraphStore`
shared a single connection across threads: every writer but the first raised
`ProgrammingError` and its edges were **lost outright** — not corrupted, simply
absent. That is the worst shape of failure here, because an absent edge looks
exactly like a repository that had nothing to say.
"""

import threading

import pytest

from evigraph.db.graph_store import Aggregate, Neighbourhood
from evigraph.db.memory_store import InMemoryGraphStore
from evigraph.db.sqlite_store import SQLiteGraphStore
from evigraph.models.graph_models import GraphEdge, GraphNode

WRITERS = 8
PER_WRITER = 25


def edge(src, dst, etype="CALLS_SERVICE"):
    return GraphEdge(source_id=src, target_id=dst, repo_id="r", type=etype,
                     evidence=["f.py:1"], detected_by="resolver.test@1",
                     created_by="linker", link_run_id="linkrun_test")


@pytest.fixture(params=["memory", "sqlite"])
def store(request):
    return (InMemoryGraphStore() if request.param == "memory"
            else SQLiteGraphStore(":memory:"))


def _run(target, count=WRITERS):
    errors = []

    def guarded(n):
        try:
            target(n)
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=guarded, args=(i,))
               for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


class TestConcurrentWrites:
    def test_no_writer_raises(self, store):
        errors = _run(lambda n: store.upsert_edges(
            [edge(f"w{n}s{i}", f"w{n}t{i}") for i in range(PER_WRITER)]))
        assert not errors, errors[:3]

    def test_no_edge_is_lost(self, store):
        _run(lambda n: store.upsert_edges(
            [edge(f"w{n}s{i}", f"w{n}t{i}") for i in range(PER_WRITER)]))
        count = store.query(Aggregate("edge")).rows[0]["count"]
        assert count == WRITERS * PER_WRITER, count

    def test_concurrent_nodes_survive(self, store):
        _run(lambda n: store.upsert_nodes(
            [GraphNode(id=f"w{n}n{i}", repo_id="r", type="File",
                       name=f"n{i}", label=f"n{i}") for i in range(PER_WRITER)]))
        count = store.query(Aggregate("node")).rows[0]["count"]
        assert count == WRITERS * PER_WRITER, count

    def test_writers_racing_on_the_same_key_converge(self, store):
        """Every writer upserts the identical edge. The MERGE key is
        (source, type, target), so the result must be exactly one — not one
        per writer, and not a partially written row."""
        errors = _run(lambda n: store.upsert_edges([edge("same", "target")]))
        assert not errors, errors[:3]
        assert store.query(Aggregate("edge")).rows[0]["count"] == 1

    def test_reads_during_writes_do_not_fail(self, store):
        """A reader on another thread must not error while writes land — a
        link run reports progress while it writes."""
        store.upsert_edges([edge("a", "b")])
        read_errors = []

        def reader(_n):
            for _ in range(20):
                store.query(Neighbourhood("a", direction="out"))

        def writer(n):
            store.upsert_edges([edge(f"x{n}", f"y{n}")])

        read_errors += _run(reader, count=3)
        read_errors += _run(writer, count=5)
        assert not read_errors, read_errors[:3]
