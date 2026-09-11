"""Skip the scan when the source has not changed.

Orchestration, and deliberately not in the store: deciding *whether* to scan
needs the scanner (parsers) and the artifact writer (store), which are
siblings — neither may import the other. Anything spanning them belongs
above both, and the layering check enforces that.

Imports nothing heavy, so a host that installed only `evigraph-core` can still
use it.
"""

import hashlib
import os
import sqlite3

from evigraph.services.file_scanner import scan_repository
from evigraph.services.scan import scan
from evigraph.db.artifact import (
    ArtifactRef, digest_of, find_artifact, read_meta, write_artifact,
)


def source_fingerprint(repo_path: str) -> str:
    """A Merkle-style digest over the files a scan would read.

    Hashes each file's path and content, then folds the sorted per-file
    digests into one. Sorted because a filesystem walk order is not stable
    across machines, and a fingerprint that changed with directory ordering
    would make every re-scan look like a change.

    Reads bytes but parses nothing, which is the point: hashing a repository
    costs a fraction of parsing it, so an unchanged repo can be skipped for
    almost nothing. Uses the same scanner the real pass uses, so the file set
    hashed is exactly the file set that would be parsed — hashing a different
    set would let a change slip through unnoticed.
    """
    per_file = []
    for info in scan_repository(repo_path).files:
        try:
            with open(info.absolute_path, "rb") as handle:
                body = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            # An unreadable file is part of the repository's state: treating
            # it as absent would make a permissions change invisible.
            body = "unreadable"
        per_file.append(f"{info.path}:{body}")

    rolled = hashlib.sha256()
    for entry in sorted(per_file):
        rolled.update(entry.encode())
        rolled.update(b"\n")
    return rolled.hexdigest()


def scan_if_changed(repo_path: str, repo_id: str, out_dir: str, *,
                    head_sha: str = "",
                    scan_fn=None) -> tuple[ArtifactRef | None, bool]:
    """Scan only when the source actually changed.

    Returns `(ref, reused)`. `reused` is True when an existing artifact still
    matches the source and no parsing was done at all — the saving is the
    whole scan, not merely the write.

    The comparison is against the artifact's *recorded* source fingerprint,
    not its own digest: two different source trees could in principle produce
    the same graph, and reusing an artifact then would be right, but claiming
    the source was unchanged would not.
    """
    current = source_fingerprint(repo_path)
    existing = find_artifact(repo_id, out_dir)
    if existing:
        try:
            recorded = read_meta(existing).get("source_digest", "")
        except sqlite3.Error:
            recorded = ""
        if recorded and recorded == current:
            meta = read_meta(existing)
            return ArtifactRef(
                path=existing, digest=digest_of(existing), repo_id=repo_id,
                nodes=int(meta.get("node_count", 0)),
                edges=int(meta.get("edge_count", 0))), True

    # `scan_fn` lets a caller substitute how the parse happens — the sharded
    # scan — while the reuse decision and the artifact write stay
    # here, identical for both. It must return what `scan()` returns.
    sink = (scan_fn or scan)(repo_path, repo_id, head_sha=head_sha)
    return write_artifact(sink, repo_id, out_dir, head_sha=head_sha,
                          source_digest=current), False


