"""One repository's scan as a single self-contained file.

A SQLite file *is* the portable artifact (architecture §5.3). One decision
covers the zero-infrastructure default, the per-repo artifact format, and
byte-level determinism at once — there is no second serialisation to keep in
step with the first.

**Content-addressed.** The name carries a digest of the bytes, so an unchanged
repository produces a byte-identical file with the same name and the whole
scan can be skipped. That is what makes incremental re-ingest possible: the
question "did this repo change?" is answered by a filename, not by a diff.

Self-contained means everything a later phase needs without the repository:
nodes, edges, per-language coverage, claim counts, and what was capped or left
unfetched. An artifact that dropped the caps would look like a complete scan
of a smaller repository — the silent truncation this codebase keeps refusing.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass

from tracekite.db.artifact_migrations import can_read, migrate
from tracekite.db.graph_store import Aggregate
from tracekite.db.sqlite_store import SQLiteGraphStore
from tracekite.wire import WIRE_VERSION

ARTIFACT_SUFFIX = ".tracekite"
DIGEST_CHARS = 16

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifact_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


@dataclass(frozen=True)
class ArtifactRef:
    """Where an artifact landed, and what it contains."""

    path: str
    digest: str
    repo_id: str
    nodes: int
    edges: int


def _meta_rows(sink, repo_id: str, head_sha: str,
               source_digest: str) -> list[tuple[str, str]]:
    """Everything about the scan that is not a node or an edge.

    Sorted and JSON-serialised with sorted keys: this table is part of the
    content that gets hashed, so map iteration order would make two identical
    scans produce two different digests.
    """
    from tracekite.answer import CONFIG_VERSION, ENGINE_VERSION
    from tracekite import engine_config

    cfg = engine_config.get_config()
    return sorted({
        "repo_id": repo_id,
        "head_sha": head_sha,
        # The source that produced this, so a re-scan can be skipped
        # without re-deriving the graph to compare it.
        "source_digest": source_digest,
        "wire_version": WIRE_VERSION,
        "node_count": str(len(sink.nodes)),
        "edge_count": str(len(sink.edges)),
        "claims": json.dumps(dict(sorted(sink.claims.items())),
                             sort_keys=True),
        "coverage": json.dumps(
            {k: v for k, v in sorted(sink.coverage.items())}, sort_keys=True,
            default=str),
        # Carried deliberately: a scan that hit a cap or skipped an unfetched
        # submodule is incomplete, and an artifact that omitted that would
        # read as a complete scan of a smaller repository.
        "capped": json.dumps(dict(sorted(getattr(sink, "capped", {}).items())),
                             sort_keys=True),
        "unfetched_submodules": json.dumps(
            sorted(getattr(sink, "unfetched_submodules", []) or [])),
        # What the scan looked for and did not find, and whether that
        # absence may be read as evidence. Without it a consumer
        # cannot tell an empty repository from an unparsed one.
        "absence": json.dumps(getattr(sink, "absence", {}),
                              sort_keys=True),
        "producer": json.dumps({
            "engine_version": ENGINE_VERSION,
            "config_version": CONFIG_VERSION,
            "wire_version": WIRE_VERSION,
            "max_files_per_repo": cfg.max_files_per_repo,
            "max_claims_per_repo": cfg.max_claims_per_repo,
        }, sort_keys=True),
    }.items())


def find_artifact(repo_id: str, out_dir: str) -> str:
    """The most recent artifact for a repo, or "" — names carry digests, so
    there may be several from different revisions."""
    if not os.path.isdir(out_dir):
        return ""
    matches = sorted(
        (os.path.join(out_dir, n) for n in os.listdir(out_dir)
         if n.startswith(f"{repo_id}-") and n.endswith(ARTIFACT_SUFFIX)),
        key=os.path.getmtime, reverse=True)
    return matches[0] if matches else ""


def write_artifact(sink, repo_id: str, out_dir: str, *,
                   head_sha: str = "", source_digest: str = "") -> ArtifactRef:
    """Write one scan to a content-addressed file. Returns where it landed.

    Built in a temporary file and packed with `VACUUM INTO` before hashing, so
    the digest covers a canonical layout rather than whatever page order the
    inserts happened to produce.
    """
    os.makedirs(out_dir, exist_ok=True)
    workdir = tempfile.mkdtemp(prefix="tracekite-artifact-")
    building = os.path.join(workdir, "building.db")
    packed = os.path.join(workdir, "packed.db")

    store = SQLiteGraphStore(building)
    store.upsert_nodes(sink.nodes)
    store.upsert_edges(sink.edges)
    with store._lock:                                    # noqa: SLF001
        store._conn.executescript(_META_SCHEMA)          # noqa: SLF001
        store._conn.executemany(                         # noqa: SLF001
            "INSERT INTO artifact_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            _meta_rows(sink, repo_id, head_sha, source_digest))
        store._conn.commit()                             # noqa: SLF001
        store._conn.execute("VACUUM INTO ?", (packed,))  # noqa: SLF001
    store.close()

    digest = hashlib.sha256(_read(packed)).hexdigest()
    name = f"{repo_id}-{digest[:DIGEST_CHARS]}{ARTIFACT_SUFFIX}"
    final = os.path.join(out_dir, name)
    os.replace(packed, final)

    return ArtifactRef(path=final, digest=digest, repo_id=repo_id,
                       nodes=len(sink.nodes), edges=len(sink.edges))


@dataclass(frozen=True)
class CompactionResult:
    """What a compaction merged, and what it refused to."""

    path: str
    artifacts: int
    repos: list[str]
    nodes: int
    edges: int
    skipped: dict[str, str]


def compact(artifact_paths, out_path: str) -> CompactionResult:
    """Merge N per-repo artifacts into one queryable index.

    Merged with ATTACH and INSERT..SELECT rather than by materialising every
    node into Python: compaction is columnar work, and at a thousand
    repositories the difference is the whole budget.

    `INSERT OR REPLACE` on the primary keys, so an artifact re-compacted after
    a re-scan supersedes its own earlier rows instead of duplicating them —
    the same identity rule the stores use (id for nodes, source+type+target
    for edges).

    An unreadable or wrong-version artifact is *skipped and named*, never
    dropped: a compaction that quietly omitted a repo would produce an index
    that looks complete and is missing an estate's worth of edges.
    """
    index = SQLiteGraphStore(out_path)
    repos, skipped = [], {}

    with index._lock:                                        # noqa: SLF001
        index._conn.executescript(_META_SCHEMA)              # noqa: SLF001
        for path in artifact_paths:
            name = os.path.basename(path)
            try:
                meta = read_meta(path)
            except (sqlite3.Error, OSError) as exc:
                skipped[name] = f"unreadable: {type(exc).__name__}"
                continue
            # An artifact outlives the code that wrote it. A minor version
            # behind is additive-only and migratable; anything else is refused
            # and named, because merging a shape nobody wrote a migration
            # for silently mixes two contracts.
            readable, reason = can_read(meta.get("wire_version", ""))
            if not readable:
                skipped[name] = reason
                continue

            # ATTACH cannot run inside an open write transaction, so each
            # artifact is merged and committed as its own unit. That also
            # means a failure part-way leaves the artifacts already merged
            # intact rather than rolling back the whole compaction.
            index._conn.commit()                             # noqa: SLF001
            index._conn.execute("ATTACH DATABASE ? AS src", (path,))  # noqa: SLF001
            try:
                index._conn.execute(
                    "INSERT OR REPLACE INTO nodes SELECT * FROM src.nodes")
                index._conn.execute(
                    "INSERT OR REPLACE INTO edges SELECT * FROM src.edges")
                index._conn.commit()                         # noqa: SLF001
            finally:
                index._conn.execute("DETACH DATABASE src")    # noqa: SLF001
            repos.append(meta.get("repo_id", name))

        index._conn.executemany(                             # noqa: SLF001
            "INSERT INTO artifact_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [("kind", "compacted-index"),
             ("wire_version", WIRE_VERSION),
             ("repos", json.dumps(sorted(repos))),
             ("skipped", json.dumps(dict(sorted(skipped.items()))))])
        index._conn.commit()                                 # noqa: SLF001

    nodes = index.query(Aggregate("node")).rows[0]["count"]
    edges = index.query(Aggregate("edge")).rows[0]["count"]
    index.close()
    return CompactionResult(path=out_path, artifacts=len(repos),
                            repos=sorted(repos), nodes=nodes, edges=edges,
                            skipped=skipped)


def read_meta(path: str) -> dict:
    """The artifact's own account of itself, without loading the graph."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT key, value FROM artifact_meta").fetchall()
    finally:
        conn.close()
    meta = dict(rows)
    for field in ("claims", "coverage", "capped", "absence", "producer",
                  "unfetched_submodules", "repos", "skipped"):
        if field in meta:
            meta[field] = json.loads(meta[field])
    return meta


def open_artifact(path: str) -> SQLiteGraphStore:
    """The artifact as a queryable store. It *is* the database."""
    return SQLiteGraphStore(path)


def digest_of(path: str) -> str:
    return hashlib.sha256(_read(path)).hexdigest()


def is_unchanged(path: str, expected_digest: str) -> bool:
    """Whether an artifact still matches a digest recorded earlier.

    The whole point of content addressing: an unchanged repository need not be
    re-scanned, and this is the question that decides it.
    """
    return bool(expected_digest) and digest_of(path) == expected_digest


def _read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()
