"""What a run cost, step by step.

Two kinds of number come out of a link run and they must not be mixed:

* **Counters** are data. `r7.decline.ambiguous = 12` is a fact about the
  estate, identical on every machine, and it travels in `LinkReport` because a
  reader needs it to know what was declined. It belongs to the wire contract.
* **Timings** are observations. 0.31 s on this laptop is 0.08 s in CI and
  neither is wrong. Putting one in an artifact would make the artifact differ
  from itself between runs, and determinism is what PR mode, caching, diffing
  and the CI gates are all built on.

So timings live here, in their own value object, and are reported to whatever
is watching — never serialised into `LinkReport`, and never read back by
anything that decides an edge.

**On the clock.** Pure layers take no clock (AGENTS.md §6), and this reads
`perf_counter`. The rule exists so that identical input yields an identical
graph; a monotonic counter that no resolver can observe and that never reaches
the result cannot change one. `test_observability.py` pins that: two runs over
the same claims produce identical edges and identical counters while their
timings differ.
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class RunTimings:
    """Wall-clock seconds per named step of one run.

    Steps accumulate rather than overwrite, so a name used twice — a resolver
    that runs in both phases, a retried stage — reports the total it actually
    cost rather than only its last attempt.
    """

    steps: dict[str, float] = field(default_factory=dict)

    def record(self, name: str, seconds: float) -> None:
        self.steps[name] = self.steps.get(name, 0.0) + seconds

    @property
    def total(self) -> float:
        return sum(self.steps.values())

    def share(self) -> dict[str, float]:
        """Each step's fraction of the total.

        The fraction is what makes a timing actionable: I2 exists to find the
        resolver costing 80% of the run, and 0.4 s only answers that question
        once you know what the other steps cost.
        """
        total = self.total
        if not total:
            return {name: 0.0 for name in self.steps}
        return {name: value / total for name, value in self.steps.items()}

    def slowest(self, limit: int = 3) -> list[tuple[str, float]]:
        """The steps worth looking at, most expensive first.

        Ties break on name so a report is stable between runs of equal-cost
        steps rather than reordering itself for no reason.
        """
        ordered = sorted(self.steps.items(), key=lambda kv: (-kv[1], kv[0]))
        return ordered[:limit]

    def as_dict(self) -> dict[str, float]:
        """Rounded to microseconds, sorted, for logs and reports.

        Rounded because the digits past a microsecond are scheduler noise, and
        printing them invites a reader to compare two runs at a precision the
        measurement does not have.
        """
        return {name: round(value, 6)
                for name, value in sorted(self.steps.items())}


@contextmanager
def timed(timings: RunTimings, name: str):
    """Record how long the block took, including when it raised.

    `finally`, not a plain trailing call: a resolver that blows up halfway is
    exactly the one whose cost you want, and losing the measurement on the
    failure path would hide the slow step behind the error it caused.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        timings.record(name, time.perf_counter() - start)
