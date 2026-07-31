"""Measure the estate pipeline: scan under N workers, then link.

`scale_probe.py` answered where the time goes (MAP, 87–94%). This answers
whether workers actually buy it back, on an estate big enough that pool
startup is noise — which the fixture corpus is not: 288 files parse in
0.62s, and measuring workers there measures overhead.

Each worker count scans into a *fresh* artifact directory. B7 skips a scan
whose source is unchanged, so a shared directory would hand every run after
the first a warm cache and report a speedup that is really a cache hit.

`--verify` checks the linked graph against the manifest's planted calls —
recall and precision by construction, at whatever scale was generated. A
timing from an estate that mislinked is not a measurement of anything.

Run: python backend/tools/estate_probe.py --estate /tmp/estate \
        [--workers 1,2,4,8] [--verify]
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.scale_probe import _skew  # noqa: E402


def measure_scan(repos: list[tuple[str, str]], workers: int,
                 hmac_key: str) -> tuple[float, list[str]]:
    from adduce.services.parallel_map import scan_many

    out_dir = tempfile.mkdtemp(prefix=f"adduce-probe-w{workers}-")
    started = time.perf_counter()
    result = scan_many(repos, out_dir, workers=workers, hmac_key=hmac_key)
    elapsed = time.perf_counter() - started
    if not result.ok:
        # A partial scan is not a slower scan, it is a different workload;
        # timing it against a complete one would compare nothing.
        raise SystemExit(f"scan failed for {sorted(result.failed)}")
    return elapsed, result.artifacts


def link_artifacts(paths: list[str]) -> tuple[float, float, object, list]:
    from adduce.db.artifact_reader import read_claims
    from adduce.services.linker.engine import link

    started = time.perf_counter()
    # Claims only: the artifacts hold the whole graph, but the link
    # needs ~2% of it, and reading the rest was 2.9s of a 5.8s repush.
    claims = [c for path in paths for c in read_claims(path)]
    read_s = time.perf_counter() - started

    started = time.perf_counter()
    result = link(claims, run_id="estate_probe",
                  now="2026-01-01T00:00:00+00:00")
    return read_s, time.perf_counter() - started, result, claims


def verify(manifest: dict, result) -> tuple[int, list, list]:
    """Planted calls vs linked graph: (planted, missing, extra)."""
    name_of = {s.service_id: s.name for s in result.services}
    found = {(name_of.get(e.source_id, e.source_id).split(":")[-1],
              name_of.get(e.target_id, e.target_id).split(":")[-1])
             for e in result.edges
             if e.type == "CALLS_SERVICE" and e.status == "active"}
    planted = {tuple(c) for c in map(tuple, manifest["calls"])}
    return len(planted), sorted(planted - found), sorted(found - planted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estate", required=True)
    parser.add_argument("--workers", default="1,2,4,8")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--repush", action="store_true",
                        help="touch one file, re-run, report the reuse")
    parser.add_argument("--hmac-key", default="estate-probe-key")
    args = parser.parse_args()

    with open(os.path.join(args.estate, "manifest.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    repos = [(repo, os.path.join(args.estate, repo))
             for repo in sorted(manifest["repos"])]

    from adduce import engine_config
    engine_config.configure(graph_hmac_key=args.hmac_key)

    print(f"{len(repos)} repos, {manifest['files']} files, "
          f"{len(manifest['calls'])} planted calls")

    artifacts, serial = [], None
    for workers in [int(w) for w in args.workers.split(",")]:
        elapsed, artifacts = measure_scan(repos, workers, args.hmac_key)
        serial = serial if serial is not None else elapsed
        print(f"  scan workers={workers}  {elapsed:7.2f}s  "
              f"{serial / elapsed:5.2f}x")

    read_s, link_s, result, claims = link_artifacts(artifacts)
    print(f"  read {read_s:.2f}s   link {link_s:.2f}s   "
          f"{len(result.edges)} edges from {len(claims)} claims")

    skew = _skew(claims)
    print(f"  skew: {skew['keys']} keys, largest holds "
          f"{skew['largest_key_claims']} claims "
          f"({skew['largest_key_share']:.1%} of matchable)")

    # The skew guard's answer: what REDUCE's worst worker would carry
    # with the hot keys split, against the naive floor without.
    from adduce.services.linker.partitions import plan
    guarded = plan(claims, workers=8)
    naive_floor = (skew["largest_key_claims"]
                   / max(1, guarded.total_claims / 8))
    print(f"  reduce plan (8 workers): tail {guarded.tail_ratio:.2f}x "
          f"(naive floor {naive_floor:.2f}x, "
          f"{len(guarded.hot_keys)} hot key(s) split, "
          f"{len(guarded.unsplittable)} declined)")

    if args.verify:
        planted, missing, extra = verify(manifest, result)
        print(f"  verify: {planted} planted, {len(missing)} missing, "
              f"{len(extra)} extra")
        if missing or extra:
            print(f"    missing: {missing[:5]}\n    extra: {extra[:5]}")
            return 1

    if args.repush:
        measure_repush(repos, artifacts, args.hmac_key)

    for path in {os.path.dirname(p) for p in artifacts}:
        shutil.rmtree(path, ignore_errors=True)
    return 0


def measure_repush(repos, artifacts: list[str], hmac_key: str) -> None:
    """One push against a scanned estate: the Phase 2 exit's second number.

    Mutates one file in one repo and re-runs the whole pipeline against the
    existing artifact directory. B7 skips every repo whose source fingerprint
    is unchanged, so the cost should be one scan plus the link — seconds,
    not the 81 minutes a serial full re-scan extrapolates to. The touched
    file gets a comment appended, which changes the fingerprint without
    changing any claim.
    """
    from adduce.services.parallel_map import scan_many

    _repo_id, repo_path = repos[0]
    # Walked, not assumed: a monorepo nests its padding under services/<svc>,
    # and the first repo in sorted order is exactly the monorepo.
    touched = next(
        os.path.join(dirpath, name)
        for dirpath, _dirs, names in sorted(os.walk(repo_path))
        for name in sorted(names) if name.endswith(".py"))
    with open(touched, "a", encoding="utf-8") as fh:
        fh.write("\n# push: one line changed\n")

    out_dir = os.path.dirname(artifacts[0])
    started = time.perf_counter()
    rescan = scan_many(repos, out_dir, workers=0, hmac_key=hmac_key)
    scan_s = time.perf_counter() - started
    read_s, link_s, _result, _claims = link_artifacts(rescan.artifacts)
    print(f"  repush: {scan_s + read_s + link_s:5.2f}s total "
          f"(scan {scan_s:.2f}s, {len(rescan.reused)}/{len(repos)} reused, "
          f"read {read_s:.2f}s, link {link_s:.2f}s)")


if __name__ == "__main__":
    sys.exit(main())
