import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor

import pytest

from tracekite import engine_config
from tracekite.services import parse_budget

fork_only = pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="the platform cannot fork")


def _parse_in_child() -> str:
    try:
        parse_budget.parse_within_budget("child.py", "y = 2\n")
    except parse_budget.ParseTimeout:
        return "timed out"
    return "parsed"


@fork_only
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
def test_a_forked_worker_parses_after_the_parent_already_has():
    # The parent parsing first is what every in-process scan does before a
    # sharded or parallel one. The forked child used to inherit the pool's
    # bookkeeping without its threads, so its parse queued behind workers that
    # did not exist and "timed out" — on Linux before Python 3.14 this dropped
    # files and made the parallel artifact differ from the serial one. Forced
    # to fork here so the test means the same thing on every platform.
    engine_config.configure(parse_timeout_s=5)
    try:
        parse_budget.parse_within_budget("parent.py", "x = 1\n")
        context = multiprocessing.get_context("fork")
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
            assert pool.submit(_parse_in_child).result(timeout=60) == "parsed"
    finally:
        engine_config.reset()


def test_a_parse_that_overruns_its_budget_is_abandoned(monkeypatch):
    release = threading.Event()

    def wedged(path, content):
        release.wait(timeout=10)

    monkeypatch.setattr(parse_budget, "parse_file", wedged)
    engine_config.configure(parse_timeout_s=1)
    try:
        with pytest.raises(parse_budget.ParseTimeout):
            parse_budget.parse_within_budget("wedged.py", "")
    finally:
        release.set()
        engine_config.reset()
