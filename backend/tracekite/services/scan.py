"""`scan()`: a repository on disk becomes claims. No server, no database.

The other half of the public contract, and the half that does the
reading. Every file is opened and parsed exactly once, and everything the pass
learns is accumulated in an `IngestSink` — an in-memory value, not a write.
Whoever called `scan()` decides what to do with it: the application writes it
to Neo4j, a library host keeps it, a CI job serialises it to an artifact.

Nothing here touches storage, which is what lets the same pass run inside
`docker compose` and inside `pip install tracekite-core` without a second
implementation drifting away from this one.
"""

import logging
import os

from tracekite.engine_config import get_config
from tracekite.services.absence import absence_report
from tracekite.services.call_graph_resolver import build_call_graph
from tracekite.services.file_parse import parse_files
from tracekite.services.file_scanner import scan_repository
from tracekite.services.graph_factories import (
    create_contains_edge, create_file_node, create_folder_node, create_repo_node,
)
from tracekite.services.ingest_source import IngestSink

logger = logging.getLogger(__name__)


def unfetched_submodules(repo_path: str) -> list[str]:
    """Submodule paths `.gitmodules` declares that are not on disk.

    An unfetched submodule is an empty directory. The scan walks it, finds
    nothing, and reports a smaller graph with no reason to doubt it — a
    silent decline at whole-repository scale, and the worst kind, because the
    missing code is exactly the shared code most likely to be called across
    repositories.

    Parsed directly rather than via a git library: `.gitmodules` is a small
    ini file, and this must work on a plain directory that was never cloned.
    """
    manifest = os.path.join(repo_path, ".gitmodules")
    if not os.path.isfile(manifest):
        return []

    declared = []
    try:
        with open(manifest, encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                key, sep, value = line.partition("=")
                if sep and key.strip() == "path":
                    declared.append(value.strip())
    except OSError:
        return []

    missing = []
    for path in declared:
        full = os.path.join(repo_path, path)
        if not os.path.isdir(full) or not os.listdir(full):
            missing.append(path)
    return sorted(missing)


def _import_scip(repo_path: str, repo_id: str, sink) -> None:
    """CI-generated index.scip, when present: the compiler's own call graph
    lands first, and the heuristic resolver fills only what it left."""
    path = os.path.join(repo_path, "index.scip")
    if not os.path.exists(path):
        return
    from tracekite.parsers.scip_parser import parse_scip
    from tracekite.services.scip_import import import_scip_calls

    with open(path, "rb") as handle:
        documents = parse_scip(handle.read())
    if documents is None:
        sink.count_claim("_scip_unreadable")
        return
    import_scip_calls(repo_id, documents, sink.parse_context, sink.nodes,
                      sink.edges, sink)


def scan(repo_path: str, repo_id: str, *, owner: str = "", repo_name: str = "",
         github_url: str = "", branch: str = "", head_sha: str = "") -> IngestSink:
    """Walk a repository and return everything it claims.

    Pure with respect to storage: the only I/O is reading the files being
    scanned. The returned sink carries nodes, edges, per-language coverage and
    claim counts — the caller persists it, or does not.
    """
    if not os.path.isdir(repo_path):
        # An empty scan of a real repository is a legitimate answer; a scan of
        # a path that is not there is not. Without this a mistyped path yields
        # an artifact that looks like a repository containing nothing, and
        # the estate is quietly short one repo.
        raise FileNotFoundError(
            f"cannot scan {repo_path!r}: not a directory. An absent "
            "repository must fail loudly, not produce an empty graph.")

    scan_result = scan_repository(repo_path)
    sink = build_graph(repo_id, owner, repo_name, github_url, branch, head_sha,
                       scan_result)
    _import_scip(repo_path, repo_id, sink)
    build_call_graph(repo_id, sink.parse_context, sink.nodes, sink.edges)

    sink.unfetched_submodules = unfetched_submodules(repo_path)
    # Recorded here, not by the writer: what a scan looked for is a fact
    # about the scan, and the store may not compute facts (architecture §2).
    sink.absence = absence_report(sink).as_dict()
    if sink.unfetched_submodules:
        logger.warning("Repo %s: %d declared submodule(s) not fetched, their "
                       "code is absent from this scan: %s", repo_id,
                       len(sink.unfetched_submodules),
                       ", ".join(sink.unfetched_submodules))
    return sink


def build_graph(repo_id: str, owner: str, repo_name: str, github_url: str,
                 branch: str, head_sha: str, scan_result) -> IngestSink:
    """Structure + single-pass parse: each file is read and parsed exactly once."""
    sink, files, file_ids = build_structure(
        repo_id, owner, repo_name, github_url, branch, head_sha, scan_result)
    sink.max_claims = get_config().max_claims_per_repo
    parse_files(repo_id, files, file_ids, sink)
    return sink


def build_structure(repo_id: str, owner: str, repo_name: str,
                    github_url: str, branch: str, head_sha: str,
                    scan_result) -> tuple[IngestSink, list, dict[str, str]]:
    """Repo, folder and file nodes — the cheap half, and the shared half.

    Split from the parse loop so a sharded scan can build structure
    once in the parent and hand each worker only a slice of `files`. Returns
    the capped file list and the file-node ids the parse needs, because the
    caller that shards is not the caller that parses.
    """
    sink = IngestSink()
    folder_ids: dict[str, str] = {}

    repo_node = create_repo_node(repo_id, owner, repo_name, github_url,
                                 branch, head_sha, scan_result.language_stats)
    sink.add_node(repo_node)

    for folder_path in scan_result.folders:
        folder_node = create_folder_node(repo_id, folder_path)
        sink.add_node(folder_node)
        folder_ids[folder_path] = folder_node.id
        parent = os.path.dirname(folder_path)
        parent_id = folder_ids.get(parent, repo_id)
        sink.add_edge(create_contains_edge(repo_id, parent_id, folder_node.id))

    file_ids: dict[str, str] = {}
    for file_info in scan_result.files:
        file_node = create_file_node(repo_id, file_info.path, file_info.name,
                                     file_info.language, file_info.size_bytes,
                                     file_info.is_test)
        sink.add_node(file_node)
        file_ids[file_info.path] = file_node.id
        parent_id = folder_ids.get(os.path.dirname(file_info.path), repo_id)
        sink.add_edge(create_contains_edge(repo_id, parent_id, file_node.id))

    # Whole-repo file ceiling. Truncating without saying so would make a
    # capped scan indistinguishable from a small repository, so the drop is
    # counted before any of it is parsed.
    cap = get_config().max_files_per_repo
    files = scan_result.files
    if cap and len(files) > cap:
        sink.capped["files"] = len(files) - cap
        logger.warning("Repo %s: %d files exceeds cap %d; %d not parsed",
                       repo_id, len(files), cap, len(files) - cap)
        files = files[:cap]
    return sink, files, file_ids
