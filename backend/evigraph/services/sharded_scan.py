"""Scan one large repository across workers.

`scan_many` shards by repository, which is the right unit until one
repository *is* the estate — the real one keeps 81% of its nodes in a
single monorepo, and repo-granular sharding leaves every other worker idle
while one parses it. This shards that repository by file: structure is
built once in the parent, contiguous slices of the ordered file list parse
in worker processes, and the chunks merge back in slice order so the result
is byte-identical to the serial scan. The determinism test compares
artifact digests, not fields — same repo, same bytes, any worker count.

The REDUCE half ("partition REDUCE by module") stays unbuilt on
purpose: the join measures 0.19s at 16.5K claims (architecture §7.5), and
partitioning it would divide milliseconds while adding a shuffle. The
measurement, not the roadmap wording, decides when that changes.

Why the claim budget forces a fallback: the serial loop stops *before* the
file that would exceed `max_claims`, so files past the cap are never
opened. Chunks cannot reproduce a mid-list break they cannot see coming, so
a merged result that hit the cap is discarded and the scan re-runs
serially — the pathological repo pays double, the normal repo pays nothing,
and the two paths never disagree about what a capped scan contains.
"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor

from evigraph.engine_config import get_config
from evigraph.services.scan import scan

logger = logging.getLogger(__name__)

# Below this many files, pool startup costs more than it buys.
SHARD_THRESHOLD_FILES = 200


def _parse_chunk(job: tuple):
    """Runs in a worker: parse one slice of files into a fresh sink."""
    repo_id, files, file_ids, hmac_key = job
    from evigraph import engine_config
    from evigraph.services.ingest_source import IngestSink
    from evigraph.services.scan import parse_files

    # A process pool does not inherit the parent's module state; a worker on
    # defaults would hash config values under an empty HMAC key and produce
    # a different graph from its siblings.
    engine_config.configure(graph_hmac_key=hmac_key)
    chunk = IngestSink()
    parse_files(repo_id, files, file_ids, chunk)
    return chunk


def scan_sharded(repo_path: str, repo_id: str, *, workers: int,
                 hmac_key: str, head_sha: str = "",
                 chunk_files: int = 64):
    """Scan one repository with its files spread across `workers`.

    Falls back to the serial `scan()` when sharding cannot help (few files,
    one worker) or cannot be correct (the merged result hit the claim cap).
    Both fallbacks return exactly what `scan()` returns, because they are
    `scan()`.
    """
    from evigraph.services.absence import absence_report
    from evigraph.services.call_graph_resolver import build_call_graph
    from evigraph.services.file_scanner import scan_repository
    from evigraph.services.scan import build_structure, unfetched_submodules
    from evigraph.services.sink_merge import merge_chunks

    if not os.path.isdir(repo_path):
        raise FileNotFoundError(
            f"cannot scan {repo_path!r}: not a directory. An absent "
            "repository must fail loudly, not produce an empty graph.")

    scan_result = scan_repository(repo_path)
    if workers <= 1 or len(scan_result.files) < SHARD_THRESHOLD_FILES:
        return scan(repo_path, repo_id, head_sha=head_sha)

    structure, files, file_ids = build_structure(
        repo_id, "", "", "", "", head_sha, scan_result)

    slices = [files[start:start + chunk_files]
              for start in range(0, len(files), chunk_files)]
    jobs = [(repo_id, chunk,
             {f.path: file_ids[f.path] for f in chunk}, hmac_key)
            for chunk in slices]

    with ProcessPoolExecutor(max_workers=workers) as pool:
        # `map` preserves argument order, which is the ordering discipline
        # the merge depends on — chunks concatenate into the exact sequence
        # the serial loop would have produced.
        chunks = list(pool.map(_parse_chunk, jobs))

    sink = merge_chunks(structure, chunks)

    cap = get_config().max_claims_per_repo
    if cap and sink.claims_total() >= cap:
        # The serial loop would have stopped mid-list; the chunks could not.
        # Re-run serially rather than serve a graph the serial scan would
        # never produce — and say so, because the double cost is real.
        logger.warning(
            "Repo %s hit the claim cap (%d) under a sharded scan; "
            "re-running serially for cap fidelity", repo_id, cap)
        return scan(repo_path, repo_id, head_sha=head_sha)

    sink.max_claims = cap
    build_call_graph(repo_id, sink.parse_context, sink.nodes, sink.edges)
    sink.unfetched_submodules = unfetched_submodules(repo_path)
    sink.absence = absence_report(sink).as_dict()
    return sink
