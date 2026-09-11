"""Measure where the time actually goes at 100 repos.

The 1,000-repo figures in the roadmap are extrapolated from six real
repositories. Designing the parallel pipeline on an extrapolation risks
parallelising the wrong phase — so this measures the constant factors and the
skew *before* B12 and B15 are built, which is the whole reason H8 precedes
them.

Two questions, and they have different answers:

* **Constant factors.** How does each phase scale with repository count? MAP
  is per-file and should be linear. The join is a hash join over a claim
  index, so it should also be near-linear — but "should be" is what this is
  for.
* **Skew.** How lopsided are the rendezvous keys? REDUCE partitions by key,
  so one popular contract with a thousand consumers serialises a shard no
  matter how many workers exist. That is B13's problem, and it cannot be
  sized without measuring.

Run: python backend/tools/scale_probe.py [--repos 100]
"""

import argparse
import os
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORPUS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "corpus")


def _replicate(count: int, into: str) -> list[tuple[str, str]]:
    """N copies of the corpus, each a distinct repository.

    Copies rather than re-pointing at one directory: distinct repo ids are
    what make the claim volume and the join realistic. Pointing every repo at
    the same path would produce identical node ids and measure deduplication
    instead of scale.
    """
    repos = []
    for i in range(count):
        for name in sorted(os.listdir(CORPUS)):
            src = os.path.join(CORPUS, name)
            if not os.path.isdir(src):
                continue
            repo_id = f"{name}-{i:04d}"
            dst = os.path.join(into, repo_id)
            shutil.copytree(src, dst)
            repos.append((repo_id, dst))
    return repos


def _skew(claims) -> dict:
    """How lopsided the rendezvous keys are.

    REDUCE partitions by key, so the largest key bounds the smallest possible
    shard: no worker count fixes a key that one worker must process alone.
    """
    counts = Counter(c.key for c in claims if c.matchable and c.key)
    if not counts:
        return {"keys": 0}
    sizes = sorted(counts.values(), reverse=True)
    total = sum(sizes)
    return {
        "keys": len(sizes),
        "largest_key_claims": sizes[0],
        "largest_key_share": round(sizes[0] / total, 4),
        "top_10_share": round(sum(sizes[:10]) / total, 4),
        "median_key_claims": statistics.median(sizes),
        # The floor on wall-clock for a perfectly parallel REDUCE: even with
        # unlimited workers, one shard carries the biggest key.
        "min_shard_share": round(sizes[0] / total, 4),
    }


def probe(count: int) -> dict:
    from tracekite import engine_config
    from tracekite.db.memory_store import InMemoryLinkerStore
    from tracekite.services.linker.engine import link
    from tracekite.services.scan import scan

    engine_config.configure(graph_hmac_key="scale-probe-key")
    workdir = tempfile.mkdtemp(prefix="tracekite-scale-")
    try:
        repos = _replicate(count, workdir)

        t = time.perf_counter()
        sinks = [scan(path, repo_id) for repo_id, path in repos]
        map_s = time.perf_counter() - t

        t = time.perf_counter()
        store = InMemoryLinkerStore(sinks)
        claims = store.load_claims()
        load_s = time.perf_counter() - t

        t = time.perf_counter()
        result = link(claims, run_id="scale_probe",
                      now="2026-01-01T00:00:00+00:00")
        join_s = time.perf_counter() - t

        return {
            "repos": len(repos),
            "files": sum(c["files_seen"] for s in sinks
                         for c in s.coverage.values()),
            "claims": len(claims),
            "edges": len(result.edges),
            "map_s": round(map_s, 3),
            "load_s": round(load_s, 3),
            "join_s": round(join_s, 3),
            "map_share": round(map_s / (map_s + load_s + join_s), 3),
            "ms_per_repo": round(1000 * (map_s + load_s + join_s) / len(repos), 1),
            "skew": _skew(claims),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", type=int, default=100)
    parser.add_argument("--curve", action="store_true",
                        help="probe several sizes to show the shape")
    args = parser.parse_args()

    sizes = [10, 25, 50, args.repos] if args.curve else [args.repos]
    for size in sizes:
        r = probe(size)
        print(f"\n=== {r['repos']} repos ({r['files']} files, "
              f"{r['claims']} claims, {r['edges']} edges) ===")
        print(f"  MAP   {r['map_s']:7.2f}s   ({r['map_share']:.0%} of total)")
        print(f"  load  {r['load_s']:7.2f}s")
        print(f"  JOIN  {r['join_s']:7.2f}s")
        print(f"  per repo: {r['ms_per_repo']} ms")
        s = r["skew"]
        print(f"  skew: {s['keys']} keys, largest holds "
              f"{s['largest_key_claims']} claims "
              f"({s['largest_key_share']:.1%}), top-10 {s['top_10_share']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
