"""Counters, timings and correlated logs (I1, I2, I3).

The three tasks are one behaviour seen from three places: a run has to be
able to say what it found, what it cost, and which run it was. Each of the
three fails silently in its own way if untested — a metric that stops being
emitted, a timing that quietly becomes part of the artifact, a log line with
no run id — so the declines are tested alongside the happy paths.
"""

import json
import logging

import pytest

from adduce.metrics_export import (
    COUNTER_METRIC, TIMING_METRIC, LoggingSink, OpenTelemetrySink,
    export_run, open_telemetry_sink,
)
from adduce.run_logging import (
    JsonFormatter, RunIdFilter, configure_logging, current_run_id,
    run_context,
)
from adduce.services.linker.base import ClaimRecord
from adduce.services.linker.engine import RESOLVERS, link
from adduce.telemetry import RunTimings, timed


def claim(cid, repo, key, hint):
    return ClaimRecord(
        id=cid, repo_id=repo, kind="svcname", direction="provides", key=key,
        service_hint=hint, hint_source="compose", matchable=True,
        evidence=["docker-compose.yml:1"], attrs={},
        evidence_node_id=None, evidence_node_type="File")


CLAIMS = [claim("c1", "repo_a", "compose:billing", "billing"),
          claim("c2", "repo_b", "compose:orders", "orders")]


def run() -> object:
    return link(CLAIMS, run_id="linkrun_obs", confidence={}, aliases={},
                promotions=[], now="2026-01-01T00:00:00+00:00")


class TestRunTimings:
    def test_repeated_steps_accumulate(self):
        """A name used twice reports its total, not its last attempt."""
        t = RunTimings()
        t.record("resolver.r7_http", 0.2)
        t.record("resolver.r7_http", 0.3)
        assert t.steps["resolver.r7_http"] == pytest.approx(0.5)
        assert t.total == pytest.approx(0.5)

    def test_share_sums_to_one(self):
        t = RunTimings()
        t.record("a", 3.0)
        t.record("b", 1.0)
        assert t.share() == {"a": 0.75, "b": 0.25}

    def test_share_of_an_empty_run_is_zero_not_a_crash(self):
        """The decline: nothing measured divides by zero unless it is
        handled, and a reporting path must never be what fails a run."""
        t = RunTimings()
        t.record("a", 0.0)
        assert t.share() == {"a": 0.0}
        assert RunTimings().share() == {}

    def test_slowest_is_stable_on_ties(self):
        t = RunTimings()
        for name in ("b", "a", "c"):
            t.record(name, 1.0)
        assert t.slowest(2) == [("a", 1.0), ("b", 1.0)]

    def test_timing_survives_an_exception(self):
        """The step that raised is the one whose cost you want."""
        t = RunTimings()
        with pytest.raises(ValueError):
            with timed(t, "boom"):
                raise ValueError("x")
        assert "boom" in t.steps


class TestLinkReportsWhatItCost:
    def test_every_resolver_and_phase_is_timed(self):
        steps = run().timings.steps
        for name, _module in RESOLVERS:
            assert f"resolver.{name}" in steps, name
        for phase in ("phase.index", "phase.broadcast", "phase.normalize",
                      "phase.join", "phase.fuse", "phase.cardinality"):
            assert phase in steps, phase

    def test_yield_is_counted_for_every_resolver_including_zero(self):
        """A resolver that stops matching drops recall without raising. An
        absent counter would read as 'not measured'; an explicit 0 says the
        resolver ran and found nothing."""
        counters = run().counters
        for name, _module in RESOLVERS:
            assert f"yield.{name}.edges" in counters, name
            assert f"yield.{name}.rendezvous" in counters, name
        assert any(counters[f"yield.{n}.edges"] == 0 for n, _ in RESOLVERS)

    def test_timings_never_reach_the_data(self):
        """Determinism is what PR mode, caching and the CI gates rest on.

        Two runs over identical claims must agree on every edge and every
        counter while disagreeing about duration — which is exactly why
        durations are a separate object and never enter `LinkReport`.
        """
        first, second = run(), run()
        assert first.counters == second.counters
        assert ([(e.type, e.source_id, e.target_id, e.confidence)
                 for e in first.edges]
                == [(e.type, e.source_id, e.target_id, e.confidence)
                    for e in second.edges])
        assert all(isinstance(v, int) for v in first.counters.values())
        assert first.timings.total > 0


class RecordingSink:
    def __init__(self):
        self.measurements = []

    def counter(self, name, value, attributes):
        self.measurements.append(("counter", name, value, attributes))

    def histogram(self, name, value, attributes):
        self.measurements.append(("histogram", name, value, attributes))


class TestMetricsExport:
    def test_counters_and_timings_are_emitted(self):
        sink = RecordingSink()
        timings = RunTimings()
        timings.record("phase.join", 0.25)

        emitted = export_run(sink, run_id="r1", counters={"a": 1, "b": 2},
                             timings=timings)

        assert emitted == 3
        kinds = [m[0] for m in sink.measurements]
        assert kinds.count("counter") == 2 and kinds.count("histogram") == 1
        assert sink.measurements[0][1] == COUNTER_METRIC
        assert sink.measurements[-1][1] == TIMING_METRIC
        assert sink.measurements[-1][3] == {
            "step": "phase.join", "run_id": "r1", "kind": "link"}

    def test_non_integer_counters_are_skipped_not_coerced(self):
        """`repos_excluded_detail` is a dict. Turning it into a number would
        invent a measurement, which is the metrics form of inventing an
        edge."""
        sink = RecordingSink()
        emitted = export_run(sink, run_id="r1", counters={
            "repos_excluded": 2,
            "repos_excluded_detail": {"repo_a": "no claims"},
            "skipped": True,
        })
        assert emitted == 1
        assert [m[3]["key"] for m in sink.measurements] == ["repos_excluded"]

    def test_a_real_link_run_exports(self):
        result = run()
        sink = RecordingSink()
        emitted = export_run(sink, run_id="linkrun_obs",
                             counters=result.counters,
                             timings=result.timings)
        assert emitted == len(result.counters) + len(result.timings.steps)

    def test_missing_opentelemetry_gives_a_reason_not_silence(self):
        """The optional dependency is absent in this environment, and the
        fallback must say so rather than emitting nothing: a dashboard that
        goes quiet looks healthy."""
        sink, reason = open_telemetry_sink()
        if sink is None:
            assert reason
        else:                                      # pragma: no cover - extra
            assert isinstance(sink, OpenTelemetrySink)

    def test_logging_sink_reports_every_measurement(self, caplog):
        with caplog.at_level(logging.INFO, logger="adduce.metrics_export"):
            export_run(LoggingSink(), run_id="r1", counters={"a": 1})
        assert any(getattr(r, "key", "") == "a" for r in caplog.records)


class FakeInstrument:
    def __init__(self):
        self.values = []

    def add(self, value, attributes):
        self.values.append((value, attributes))

    def record(self, value, attributes):
        self.values.append((value, attributes))


class FakeMeter:
    def __init__(self):
        self.created = []

    def create_counter(self, name, **kw):
        self.created.append(name)
        return FakeInstrument()

    def create_histogram(self, name, **kw):
        self.created.append(name)
        return FakeInstrument()


class TestOpenTelemetrySink:
    def test_instruments_are_created_once_and_reused(self):
        """One registration per metric, not per measurement: a long-running
        server exporting per call leaks until memory objects."""
        meter = FakeMeter()
        sink = OpenTelemetrySink(meter)
        for _ in range(5):
            sink.counter(COUNTER_METRIC, 1, {"key": "a"})
            sink.histogram(TIMING_METRIC, 0.1, {"step": "s"})
        assert meter.created == [COUNTER_METRIC, TIMING_METRIC]


def _service(on_run):
    from adduce.db.memory_store import InMemoryLinkerStore
    from adduce.services.linker.service import LinkerService

    store = InMemoryLinkerStore([])
    return LinkerService(store, on_run=on_run), store


class TestRunObserver:
    def test_the_hook_receives_the_run_id_counters_and_timings(self):
        seen = []
        service, _store = _service(lambda *args: seen.append(args))
        out = service.link_full()

        assert len(seen) == 1
        run_id, counters, timings = seen[0]
        assert run_id == out["link_run_id"]
        assert counters["claims_loaded"] == 0
        assert timings.total > 0

    def test_a_failing_observer_does_not_fail_the_run(self, caplog):
        """Publishing a measurement is the least important thing a run does.
        An exporter that is down must not turn a completed link into a failed
        one — but it must also not be silent about it."""
        def boom(*_args):
            raise RuntimeError("collector unreachable")

        service, store = _service(boom)
        with caplog.at_level(logging.WARNING):
            out = service.link_full()

        assert out["link_run_id"]
        assert store.link_runs[-1]["status"] == "done"
        assert any("run observer failed" in r.getMessage()
                   for r in caplog.records)


class TestCorrelatedLogs:
    def test_ambient_run_id_is_attached(self):
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
        with run_context("linkrun_abc"):
            assert current_run_id() == "linkrun_abc"
            RunIdFilter().filter(record)
        assert record.link_run_id == "linkrun_abc"

    def test_an_explicit_run_id_wins(self):
        """A line may describe a run other than the ambient one; the caller
        that knows which is right must not be overwritten."""
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
        record.link_run_id = "linkrun_explicit"
        with run_context("linkrun_ambient"):
            RunIdFilter().filter(record)
        assert record.link_run_id == "linkrun_explicit"

    def test_outside_a_run_the_field_is_empty_not_invented(self):
        record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
        RunIdFilter().filter(record)
        assert record.link_run_id == ""

    def test_json_formatter_emits_extras(self):
        record = logging.LogRecord("app.x", logging.INFO, "f", 1,
                                   "linked %d", (3,), None)
        record.link_run_id = "linkrun_abc"
        record.resolver = "r7_http"
        payload = json.loads(JsonFormatter().format(record))
        assert payload["msg"] == "linked 3"
        assert payload["link_run_id"] == "linkrun_abc"
        assert payload["resolver"] == "r7_http"
        assert payload["level"] == "INFO"

    def test_unserialisable_extras_do_not_lose_the_line(self):
        record = logging.LogRecord("app.x", logging.INFO, "f", 1, "m",
                                   None, None)
        record.thing = object()
        assert json.loads(JsonFormatter().format(record))["thing"]

    def test_configuring_twice_does_not_duplicate_lines(self, capsys):
        """Called by the CLI and again by what it starts, the naive version
        prints everything twice and the duplicates look like duplicate work."""
        import sys as _sys
        try:
            configure_logging(json_format=True, level=logging.INFO,
                              stream=_sys.stderr)
            configure_logging(json_format=True, level=logging.INFO,
                              stream=_sys.stderr)
            logging.getLogger("app.dupe").info("once")
            lines = [ln for ln in capsys.readouterr().err.splitlines()
                     if "app.dupe" in ln]
            assert len(lines) == 1, lines
        finally:
            root = logging.getLogger()
            for h in list(root.handlers):
                if getattr(h, "_adduce_configured", False):
                    root.removeHandler(h)

    def test_one_run_is_reconstructable_from_logs(self, caplog):
        """I3's exit criterion, asserted rather than described.

        Both halves matter and they are different mechanisms. A module that
        has never heard of a LinkRun — a parser, the store — is correlated by
        the ambient context alone; the linker, which knows the id, stamps it
        explicitly and that wins. Testing only the second would pass with the
        contextvar removed, which is most of what I3 is.
        """
        caplog.handler.addFilter(RunIdFilter())
        with caplog.at_level(logging.INFO):
            with run_context("job_42"):
                run()
                logging.getLogger("adduce.parsers.imaginary").info("read a file")

        ambient = [r for r in caplog.records
                   if r.name == "adduce.parsers.imaginary"]
        assert ambient
        assert all(r.link_run_id == "job_42" for r in ambient)

        linker = [r for r in caplog.records
                  if r.name.startswith("adduce.services.linker")]
        assert linker
        assert all(r.link_run_id == "linkrun_obs" for r in linker)
        assert sum("Linker r7_http" in r.getMessage() for r in linker) == 1
