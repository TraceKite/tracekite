"""Wall-clock and peak memory per 100k LOC, per commit.

Absolute numbers drift with hardware; per-100k-LOC numbers drift with the
code, which is the drift worth tracking. The estate is generated fresh
from a fixed seed each run — same seed, same bytes — so two commits'
benchmarks measure the same workload, and the runner's only variables are
the machine and the code under test.

Peak memory is read in a CHILD process per stage: getrusage's high-water
mark never goes down, so measuring scan and link in one process would
charge the link with the scan's peak.

Run: python backend/tools/benchmark.py [--repos 40] [--out benchmarks.json]
"""

import argparse
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_STAGE_PROGRAM = """
import json, resource, sys, time
sys.path.insert(0, {backend!r})
from evigraph import engine_config
engine_config.configure(graph_hmac_key="benchmark-key")

stage = {stage!r}
started = time.perf_counter()
if stage == "scan":
    from evigraph.services.parallel_map import scan_many
    repos = json.load(open({repos_file!r}))
    result = scan_many([tuple(r) for r in repos], {out_dir!r}, workers=0,
                       hmac_key="benchmark-key")
    assert result.ok, result.failed
    payload = {{"artifacts": len(result.artifacts)}}
else:
    from evigraph.db.artifact_reader import read_claims
    from evigraph.services.linker.engine import link
    paths = json.load(open({repos_file!r}))
    claims = [c for p in paths for c in read_claims(p)]
    result = link(claims, run_id="benchmark",
                  now="2026-01-01T00:00:00+00:00")
    payload = {{"claims": len(claims), "edges": len(result.edges)}}

peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform == "darwin":
    peak //= 1024                       # bytes on macOS, KiB elsewhere
print(json.dumps({{"seconds": round(time.perf_counter() - started, 3),
                   "peak_kib": peak, **payload}}))
"""


def _run_stage(stage: str, repos_file: str, out_dir: str) -> dict:
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    program = _STAGE_PROGRAM.format(backend=backend, stage=stage,
                                    repos_file=repos_file, out_dir=out_dir)
    proc = subprocess.run([sys.executable, "-c", program],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0:
        raise SystemExit(f"{stage} failed:\n{proc.stderr}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def count_loc(root: str) -> int:
    total = 0
    for dirpath, _dirs, names in os.walk(root):
        for name in names:
            try:
                with open(os.path.join(dirpath, name), "rb") as fh:
                    total += fh.read().count(b"\n")
            except OSError:
                continue
    return total


def benchmark(repos: int, seed: int) -> dict:
    from tools.synth_estate import generate

    workdir = tempfile.mkdtemp(prefix="evigraph-bench-")
    try:
        estate_dir = os.path.join(workdir, "estate")
        manifest = generate(estate_dir, repos=repos, seed=seed)
        loc = count_loc(estate_dir)

        repos_file = os.path.join(workdir, "repos.json")
        with open(repos_file, "w", encoding="utf-8") as fh:
            json.dump([[r, os.path.join(estate_dir, r)]
                       for r in sorted(manifest["repos"])], fh)
        artifacts_dir = os.path.join(workdir, "artifacts")

        scan_stats = _run_stage("scan", repos_file, artifacts_dir)
        paths_file = os.path.join(workdir, "paths.json")
        with open(paths_file, "w", encoding="utf-8") as fh:
            json.dump(sorted(
                os.path.join(artifacts_dir, n)
                for n in os.listdir(artifacts_dir)), fh)
        link_stats = _run_stage("link", paths_file, artifacts_dir)

        per = 100_000 / max(loc, 1)
        return {
            "estate": {"repos": repos, "seed": seed, "loc": loc,
                       "files": manifest["files"]},
            "scan": scan_stats, "link": link_stats,
            "per_100k_loc": {
                "scan_seconds": round(scan_stats["seconds"] * per, 3),
                "link_seconds": round(link_stats["seconds"] * per, 3),
                "scan_peak_mib": round(scan_stats["peak_kib"] * per / 1024, 1),
                "link_peak_mib": round(link_stats["peak_kib"] * per / 1024, 1),
            },
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", type=int, default=40)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = benchmark(args.repos, args.seed)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
