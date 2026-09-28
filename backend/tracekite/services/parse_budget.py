"""A per-file time budget for parsing, safe to use from forked workers.

A pathological file can wedge tree-sitter indefinitely (design §3 guardrails,
GitNexus), and without a cap one file stalls an entire repo's ingest. So each
parse runs on a small shared thread pool and is abandoned once it overruns —
Python cannot interrupt the thread, but the ingest moves on.

That pool must not cross a fork. Sharded and parallel scans start workers with
fork() wherever it is the default (Linux before Python 3.14), and a forked child
inherits an executor's bookkeeping but none of its threads. Once the parent had
parsed anything, every parse in the child queued behind workers that did not
exist, "timed out" after its full budget and was dropped, so the parallel
artifact silently differed from the serial one. Each forked child therefore
starts with a pool of its own.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from tracekite.engine_config import get_config
from tracekite.parsers.parser_registry import parse_file


class ParseTimeout(RuntimeError):
    """A single file exceeded its parse budget."""


def _new_pool() -> ThreadPoolExecutor:
    # One shared executor: ingest workers already bound concurrency, and a
    # per-file thread would cost more than the parse for the common case.
    return ThreadPoolExecutor(max_workers=2, thread_name_prefix="parse")


_pool = _new_pool()


def _replace_pool_in_child() -> None:
    global _pool
    _pool = _new_pool()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_replace_pool_in_child)


def parse_within_budget(path: str, content: str):
    """Parse one file, or raise ParseTimeout once it overruns its budget."""
    future = _pool.submit(parse_file, path, content)
    try:
        return future.result(timeout=get_config().parse_timeout_s)
    except FuturesTimeout as exc:
        future.cancel()
        raise ParseTimeout(path) from exc
