"""Every log line from a run carries that run's id.

The exit criterion is that one run is reconstructable from logs. Today it very
nearly isn't: the linker logs a line per resolver, the parsers log per file,
the store logs per write, and two concurrent runs interleave into a single
stream where no line says which run it belongs to. Reconstructing one means
guessing from timestamps, which stops working at exactly the moment it matters
— when something is running twice.

So the id is attached by a filter rather than by asking every call site to
pass it. A parser three layers down cannot know a LinkRun exists, and
threading the id through its signature would couple the parse layer to the
linker to satisfy a logging concern. A context variable it never sees does the
same job and leaves it pure.

`extra={"link_run_id": ...}` at a call site still wins — the engine already
passes it explicitly, and an explicit value is right when a line describes a
run other than the ambient one.
"""

import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar

# Set for the duration of a run. A ContextVar rather than a global because
# asyncio tasks and threads each get their own view: two runs in one process
# must not stamp each other's lines.
_current_run: ContextVar[str] = ContextVar("tracekite_run_id", default="")

# LogRecord's own attributes. Anything else on a record arrived via `extra`
# and is a field worth emitting — that is what makes the log structured
# rather than a string with a prefix.
_BUILTIN = frozenset(vars(logging.LogRecord(
    "", 0, "", 0, "", None, None)).keys()) | {"message", "asctime",
                                              "taskName"}


@contextmanager
def run_context(run_id: str):
    """Stamp every log line emitted inside this block with `run_id`."""
    token = _current_run.set(run_id)
    try:
        yield
    finally:
        _current_run.reset(token)


def current_run_id() -> str:
    return _current_run.get()


class RunIdFilter(logging.Filter):
    """Attach the ambient run id to records that do not already carry one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "link_run_id", ""):
            record.link_run_id = _current_run.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, extras included.

    `default=str` on the dump: a log line must never be the thing that raises.
    A value that will not serialise is worth its repr — losing the line to a
    TypeError would lose the run it was describing.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        run_id = getattr(record, "link_run_id", "")
        if run_id:
            payload["link_run_id"] = run_id
        for key, value in vars(record).items():
            if key not in _BUILTIN and key != "link_run_id":
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


class TextFormatter(logging.Formatter):
    """Human-readable, with the run id in front when there is one."""

    def format(self, record: logging.LogRecord) -> str:
        run_id = getattr(record, "link_run_id", "")
        prefix = f"[{run_id}] " if run_id else ""
        return f"{record.levelname:<7} {prefix}{record.name}: " \
               f"{record.getMessage()}"


def wants_json(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("TRACEKITE_LOG_FORMAT", "").lower() == "json"


def configure_logging(*, json_format: bool | None = None, level: int = None,
                      stream=None) -> logging.Handler:
    """Install one correlated handler on the root logger, and return it.

    Replaces any handler this function installed before, rather than stacking
    a second one: called twice — once by the CLI, once by the server that the
    CLI started — the naive version prints everything twice and the duplicate
    lines look like duplicate work.
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        if getattr(existing, "_tracekite_configured", False):
            root.removeHandler(existing)

    use_json = wants_json() if json_format is None else json_format
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter() if use_json else TextFormatter())
    handler.addFilter(RunIdFilter())
    handler._tracekite_configured = True                          # noqa: SLF001
    root.addHandler(handler)
    if level is not None:
        root.setLevel(level)
    return handler
