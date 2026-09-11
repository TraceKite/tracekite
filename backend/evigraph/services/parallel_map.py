"""Scan many repositories at once.

A scale probe measured where the time actually goes: the join is 0.03 s over
the live estate, and MAP is 87–94% of everything. So this parallelises MAP.
Splitting the join would divide thirty milliseconds — architecture §4 records
that finding, and REDUCE partitioning waits on it becoming measurable.

**Workers return artifact paths, not graphs.** A process pool must pickle
whatever a worker returns, and a scanned estate is tens of thousands of nodes;
sending them back through a pipe would spend more on serialisation than the
parse saved. Each worker writes its artifact and returns the path, which
is what the artifact format was for — the parallel pipeline is the composition
of pieces that already exist, not new machinery.

Processes rather than threads: parsing is CPU-bound and tree-sitter does not
release the GIL predictably across grammars, so threads would serialise the
one phase worth parallelising.
"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MapResult:
    """What a parallel MAP produced, including what failed."""

    artifacts: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    reused: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _head_sha(repo_path: str) -> str:
    """The commit this scan represents, or "" if the path is not a checkout.

    Not optional decoration: "the graph at commit X" is a link over the
    artifacts at X (architecture §3.4), so an artifact with no commit cannot
    take part in any temporal answer. Returning "" rather than raising keeps a
    non-git directory scannable — the corpus fixtures are ordinary folders —
    but the artifact then carries no anchor, and `evigraph history` says so by
    falling back to a positional label instead of inventing a sha.
    """
    try:
        from evigraph.services.repo_service import get_head_commit_sha

        return get_head_commit_sha(repo_path)
    except Exception:                                         # noqa: BLE001
        return ""


def _scan_one(job: tuple) -> tuple:
    """Runs in a worker. Returns (repo_id, path, reused, error).

    Configures the engine inside the worker: a process pool does not inherit
    the parent's module state, and a worker running on defaults would hash
    config values under an empty HMAC key — silently producing a different
    graph from its siblings.
    """
    repo_id, repo_path, out_dir, hmac_key = job
    try:
        from evigraph import engine_config
        from evigraph.services.reingest import scan_if_changed

        engine_config.configure(graph_hmac_key=hmac_key)
        ref, reused = scan_if_changed(repo_path, repo_id, out_dir,
                                      head_sha=_head_sha(repo_path))
        return repo_id, ref.path, reused, ""
    except Exception as exc:                                  # noqa: BLE001
        # Returned rather than raised: one unparseable repository must not
        # take down the estate's scan, and a failure nobody records is the
        # silent absence this codebase keeps refusing.
        return repo_id, "", False, f"{type(exc).__name__}: {exc}"[:200]


def scan_many(repos, out_dir: str, *, workers: int = 0,
              hmac_key: str = "") -> MapResult:
    """Scan every repository, in parallel, into content-addressed artifacts.

    `repos` is an iterable of `(repo_id, path)`. `workers` defaults to the
    machine's CPU count; 1 runs inline, which is what the tests use to compare
    against the parallel result.

    Unchanged repositories are skipped entirely, so a re-scan of a mostly
    static estate costs almost nothing however many workers there are.
    """
    from evigraph.engine_config import get_config

    key = hmac_key or get_config().graph_hmac_key
    count = workers or os.cpu_count() or 1

    # A repository big enough to dominate the estate gets its FILES sharded
    # across the pool instead of occupying one worker while the rest idle
    # — the real estate keeps 81% of its nodes in one monorepo, and
    # repo-granular sharding caps the whole scan at that repo's serial time.
    # Raw file count over-counts (no ignore rules), which only mis-routes a
    # repo into scan_sharded's own threshold check — never the reverse.
    big, small = [], []
    for repo_id, path in repos:
        (big if count > 1 and _raw_file_count(path) >= _BIG_REPO_FILES
         else small).append((repo_id, path))

    jobs = [(repo_id, path, out_dir, key) for repo_id, path in small]
    result = MapResult()

    if count == 1:
        for job in jobs:
            _collect(result, _scan_one(job))
    else:
        with ProcessPoolExecutor(max_workers=count) as pool:
            futures = [pool.submit(_scan_one, job) for job in jobs]
            for future in as_completed(futures):
                _collect(result, future.result())

    for repo_id, path in big:
        # Sequential phases are not a compromise: each phase saturates the
        # pool, so small/W + Σ big/W is the same wall-clock as one perfectly
        # scheduled pool — without two levels of process nesting.
        _collect(result, _scan_one_sharded(repo_id, path, out_dir, key,
                                           count))

    # Sorted so a parallel run and a serial run produce the same list: the
    # order futures complete in is not deterministic, and an artifact list
    # that changed order between runs would break every downstream diff.
    result.artifacts.sort()
    result.reused.sort()
    return result


# Routed to the file-sharded path at or above this raw (unfiltered) count.
_BIG_REPO_FILES = 300


def _raw_file_count(path: str) -> int:
    count = 0
    for _dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in (".git",)]
        count += len(filenames)
        if count >= _BIG_REPO_FILES:
            return count
    return count


def _scan_one_sharded(repo_id: str, repo_path: str, out_dir: str,
                      hmac_key: str, workers: int) -> tuple:
    """The monorepo path: same reuse, same artifact, files spread out."""
    try:
        from evigraph.services.reingest import scan_if_changed
        from evigraph.services.sharded_scan import scan_sharded

        def sharded(path, rid, *, head_sha=""):
            return scan_sharded(path, rid, workers=workers,
                                hmac_key=hmac_key, head_sha=head_sha)

        ref, reused = scan_if_changed(
            repo_path, repo_id, out_dir, head_sha=_head_sha(repo_path),
            scan_fn=sharded)
        return repo_id, ref.path, reused, ""
    except Exception as exc:                                  # noqa: BLE001
        return repo_id, "", False, f"{type(exc).__name__}: {exc}"[:200]


def _collect(result: MapResult, outcome: tuple) -> None:
    repo_id, path, reused, error = outcome
    if error:
        result.failed[repo_id] = error
        logger.warning("scan failed for %s: %s", repo_id, error)
        return
    result.artifacts.append(path)
    if reused:
        result.reused.append(repo_id)
