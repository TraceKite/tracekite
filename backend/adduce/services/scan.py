"""`scan()`: a repository on disk becomes claims. No server, no database.

The other half of the public contract, and the half that does the
reading. Every file is opened and parsed exactly once, and everything the pass
learns is accumulated in an `IngestSink` — an in-memory value, not a write.
Whoever called `scan()` decides what to do with it: the application writes it
to Neo4j, a library host keeps it, a CI job serialises it to an artifact.

Nothing here touches storage, which is what lets the same pass run inside
`docker compose` and inside `pip install adduce-core` without a second
implementation drifting away from this one.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout

from adduce.engine_config import get_config
from adduce.parsers.parser_registry import get_parser_for_file, parse_file
from adduce.parsers.tree_sitter.adapter import TreeSitterSourceParser
from adduce.services.absence import absence_report
from adduce.services.call_graph_resolver import build_call_graph
from adduce.services.file_scanner import scan_repository
from adduce.services.graph_factories import (
    create_contains_edge, create_file_node, create_folder_node, create_repo_node,
)
from adduce.services.ingest_artifacts import (
    process_agent_card, process_asyncapi, process_avro, process_buf,
    process_catalog, process_codeowners, process_config, process_dependencies,
    process_docker, process_gateway, process_graphql, process_iac,
    process_k8s, process_mcp_config, process_migration, process_observability,
    process_cron, process_iac_units, process_openapi,
    process_pipeline, process_proto, process_publish,
)
from adduce.services.ingest_claims import (
    emit_mcp_manifest_claims, emit_source_claims,
)
from adduce.services.ingest_source import IngestSink, process_source_file

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
    from adduce.parsers.scip_parser import parse_scip
    from adduce.services.scip_import import import_scip_calls

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


def parse_files(repo_id: str, files: list, file_ids: dict[str, str],
                sink: IngestSink) -> None:
    """Parse a slice of files into `sink` — the expensive half.

    The claim-budget break stops *before* a file, so a capped serial scan
    never opens the files past the cap. A sharded caller cannot reproduce
    that mid-list break across chunks; it detects the cap at merge and
    re-runs serially instead (see `sharded_scan.py`).
    """
    for file_info in files:
        if sink.claim_budget_exhausted():
            break
        _parse_one_file(repo_id, file_info, file_ids[file_info.path], sink)


class _ParseTimeout(RuntimeError):
    """A single file exceeded its parse budget."""


# One shared executor: ingest workers already bound concurrency, and a
# per-file thread would cost more than the parse for the common case.
_parse_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="parse")


def _parse_with_timeout(path: str, content: str):
    """Bound a single file's parse (design §3 guardrails, GitNexus).

    A pathological file can wedge tree-sitter indefinitely; without a cap one
    file stalls an entire repo's ingest. The worker thread is abandoned rather
    than killed — Python cannot interrupt it — but the ingest moves on.
    """
    future = _parse_pool.submit(parse_file, path, content)
    try:
        return future.result(timeout=get_config().parse_timeout_s)
    except FuturesTimeout as exc:
        future.cancel()
        raise _ParseTimeout(path) from exc


def _parse_one_file(repo_id: str, file_info, file_node_id: str,
                    sink: IngestSink) -> None:
    counters = sink.lang(file_info.language)
    counters["files_seen"] += 1

    if file_info.size_bytes > get_config().parse_file_cap_bytes:
        counters["files_skipped_large"] += 1
        return

    try:
        with open(file_info.absolute_path, "r", encoding="utf-8",
                  errors="ignore") as handle:
            content = handle.read()
    except OSError as exc:
        counters["parse_errors"] += 1
        logger.debug("Cannot read %s: %s", file_info.path, exc)
        return

    try:
        result = _parse_with_timeout(file_info.path, content)
    except _ParseTimeout:
        counters["parse_errors"] += 1
        counters["parse_timeouts"] = counters.get("parse_timeouts", 0) + 1
        logger.warning("Parse timed out after %ds for %s",
                       get_config().parse_timeout_s, file_info.path)
        return
    except Exception as exc:
        counters["parse_errors"] += 1
        logger.warning("Parse failed for %s: %s", file_info.path, exc)
        return

    source = result.get("source_result")
    if source is not None and not source.errors:
        parser = get_parser_for_file(file_info.path)
        tier = "full" if isinstance(parser, TreeSitterSourceParser) else "lite"
        process_source_file(repo_id, file_info, source, file_node_id, sink, tier,
                            content=content)
    elif source is not None and source.errors:
        counters["parse_errors"] += 1
        # Symbols from a broken parse are untrustworthy, but HTTP call sites are
        # extracted by regex over raw text and are unaffected — dropping them
        # loses consumer-side recall for the exact files most likely to be
        # partially parseable.
        emit_source_claims(repo_id, file_info, content, [], file_node_id, sink)

    if deps := result.get("dependencies"):
        process_dependencies(repo_id, file_info, deps, file_node_id, sink,
                             content=content)
    if config_result := result.get("config"):
        process_config(repo_id, file_info, config_result, file_node_id, sink)
    if docker := result.get("docker"):
        process_docker(repo_id, file_info, docker, file_node_id, sink)
    if k8s := result.get("kubernetes"):
        process_k8s(repo_id, file_info, k8s, file_node_id, sink)
    if iac := result.get("iac"):
        process_iac(repo_id, file_info, iac, file_node_id, sink)
    if proto := result.get("proto"):
        process_proto(repo_id, file_info, proto, file_node_id, sink)
    if buf := result.get("buf"):
        process_buf(repo_id, file_info, buf, file_node_id, sink)
    if graphql := result.get("graphql"):
        process_graphql(repo_id, file_info, graphql, file_node_id, sink)
    if asyncapi := result.get("asyncapi"):
        process_asyncapi(repo_id, file_info, asyncapi, file_node_id, sink)
    if mcp_manifest := result.get("mcp_manifest"):
        emit_mcp_manifest_claims(repo_id, file_info, mcp_manifest,
                                 file_node_id, sink)
    if avro := result.get("avro"):
        process_avro(repo_id, file_info, avro, file_node_id, sink)
    if publish := result.get("publish"):
        process_publish(repo_id, file_info, publish, file_node_id, sink,
                        content=content)
    if gateway := result.get("gateway"):
        process_gateway(repo_id, file_info, gateway, file_node_id, sink)
    if codeowners := result.get("codeowners"):
        process_codeowners(repo_id, file_info, codeowners, file_node_id, sink)
    if catalog := result.get("catalog"):
        process_catalog(repo_id, file_info, catalog, file_node_id, sink)
    if observability := result.get("observability"):
        process_observability(repo_id, file_info, observability,
                              file_node_id, sink)
    if pipeline := result.get("pipeline"):
        process_pipeline(repo_id, file_info, pipeline, file_node_id, sink)
    if result.get("migration"):
        process_migration(repo_id, file_info, content, file_node_id, sink)
    if mcp_config := result.get("mcp_config"):
        process_mcp_config(repo_id, file_info, mcp_config, file_node_id, sink)
    if agent_card := result.get("agent_card"):
        process_agent_card(repo_id, file_info, agent_card, file_node_id, sink)
    if cron := result.get("cron"):
        process_cron(repo_id, file_info, cron, file_node_id, sink)
    if iac_units := result.get("iac_units"):
        process_iac_units(repo_id, file_info, iac_units,
                          file_node_id, sink)
    if openapi := result.get("openapi"):
        process_openapi(repo_id, file_info, openapi,
                        file_node_id, sink)
