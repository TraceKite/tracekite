"""Publish a run's counters and timings to whatever is watching.

The counters have existed since the first resolver; nothing outside a JSON
response could see them. This exports them, which is the whole of I1 — the
numbers are not new, their visibility is.

**OpenTelemetry is optional and must stay optional.** `pip install
adduce-core` promises no server and no database; adding a metrics SDK to the
required set would make an embedding host adopt an observability stack to run
a join. So the OTel sink is built only if the package imports, and when it
does not, export falls back to a structured log line rather than doing
nothing. A metric that silently stops being emitted is the observability
equivalent of a silently dropped edge: the dashboard goes quiet and looks
healthy.

`export_run` returns how many measurements it emitted, so a caller can tell
"nothing to report" from "nowhere to report it".
"""

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# One metric name per kind, with the specific key as an attribute, rather than
# a metric per counter. Counter keys are open-ended — every resolver invents
# its own decline reasons — and a metric namespace that grows whenever someone
# adds a `ctx.count()` cannot be charted or aggregated.
COUNTER_METRIC = "adduce.link.counter"
TIMING_METRIC = "adduce.link.step_seconds"


@runtime_checkable
class MetricSink(Protocol):
    """Where measurements go. Two methods, because that is all this needs."""

    def counter(self, name: str, value: int, attributes: dict) -> None: ...

    def histogram(self, name: str, value: float, attributes: dict) -> None: ...


class LoggingSink:
    """The fallback: one structured log line per measurement.

    Not a null sink. If the only thing available is a log file, the counters
    still have to arrive somewhere a person can grep — the point of I1 is that
    a decline stops being invisible, and "we had no exporter configured" is
    not a reason to make it invisible again.
    """

    def __init__(self, level: int = logging.INFO):
        self._level = level

    def counter(self, name: str, value: int, attributes: dict) -> None:
        logger.log(self._level, "metric %s=%d", name, value,
                   extra={"metric": name, "value": value, **attributes})

    def histogram(self, name: str, value: float, attributes: dict) -> None:
        logger.log(self._level, "metric %s=%.6f", name, value,
                   extra={"metric": name, "value": value, **attributes})


class OpenTelemetrySink:
    """Adapts an OpenTelemetry `Meter` to the two methods above.

    Instruments are created once and reused: creating a counter per call is
    permitted by the API but leaks a registration on every measurement, and
    the SDK will happily let a long-running server do it until memory says
    otherwise.
    """

    def __init__(self, meter):
        self._counters: dict[str, object] = {}
        self._histograms: dict[str, object] = {}
        self._meter = meter

    def counter(self, name: str, value: int, attributes: dict) -> None:
        instrument = self._counters.get(name)
        if instrument is None:
            instrument = self._meter.create_counter(name)
            self._counters[name] = instrument
        instrument.add(value, attributes)

    def histogram(self, name: str, value: float, attributes: dict) -> None:
        instrument = self._histograms.get(name)
        if instrument is None:
            instrument = self._meter.create_histogram(name, unit="s")
            self._histograms[name] = instrument
        instrument.record(value, attributes)


def open_telemetry_sink() -> tuple[MetricSink | None, str]:
    """An OTel sink, or None and the reason there isn't one.

    The reason is returned rather than logged here so the caller decides how
    loud it should be: a library host that never wanted metrics should not see
    a warning on every run, and a server that configured an exporter and got
    nothing should see exactly one.
    """
    try:
        from opentelemetry import metrics
    except ImportError:
        return None, ("opentelemetry is not installed; it is an optional "
                      "extra, so this is only a problem if you expected "
                      "metrics")
    try:
        meter = metrics.get_meter("adduce")
    except Exception as exc:                                  # noqa: BLE001
        return None, f"opentelemetry present but unusable: {exc}"
    return OpenTelemetrySink(meter), ""


def default_sink() -> MetricSink:
    """OTel when it is there, structured logs when it is not."""
    sink, reason = open_telemetry_sink()
    if sink is not None:
        return sink
    logger.debug("metrics falling back to logs: %s", reason)
    return LoggingSink()


def export_run(sink: MetricSink, *, run_id: str, counters: dict,
               timings=None, kind: str = "link") -> int:
    """Emit one run's counters and timings. Returns the measurement count.

    Non-integer counters are skipped and counted as skipped, not coerced:
    `repos_excluded_detail` is a dict, and turning it into a number would
    invent a measurement. The skip is reported in the return value's absence
    rather than swallowed.
    """
    emitted = 0
    for key, value in sorted(counters.items()):
        if not isinstance(value, int) or isinstance(value, bool):
            continue
        sink.counter(COUNTER_METRIC, value,
                     {"key": key, "run_id": run_id, "kind": kind})
        emitted += 1

    for step, seconds in sorted((timings.as_dict() if timings else {}).items()):
        sink.histogram(TIMING_METRIC, seconds,
                       {"step": step, "run_id": run_id, "kind": kind})
        emitted += 1
    return emitted
