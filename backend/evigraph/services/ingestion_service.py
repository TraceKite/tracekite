"""Repository ingestion pipeline: clone → scan → parse → (clear) → write.

Refresh safety (design §5.2): the new tree is fully parsed *before* the old
graph is cleared, so a failed clone or parse leaves the previous graph intact
(failed_clean). Only a failure after clearing yields failed_partial.
"""

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Optional

from evigraph.config import settings
from evigraph.db.neo4j_client import get_session
from evigraph.models.graph_models import GraphEdge, GraphNode
from evigraph.parsers.parser_registry import get_parser_for_file, parse_file
from evigraph.parsers.tree_sitter.adapter import TreeSitterSourceParser
from evigraph.services import graph_writer
from evigraph.services.call_graph_resolver import build_call_graph
from evigraph.services.file_scanner import scan_repository
from evigraph.services.graph_factories import (
    create_contains_edge, create_file_node, create_folder_node, create_repo_node,
)
from evigraph.services.ingest_artifacts import (
    process_agent_card, process_asyncapi, process_avro, process_buf,
    process_catalog, process_codeowners, process_config, process_dependencies,
    process_docker, process_gateway, process_graphql, process_iac,
    process_k8s, process_mcp_config, process_migration, process_observability,
    process_pipeline, process_proto, process_publish,
)
from evigraph.services.ingest_claims import (
    emit_mcp_manifest_claims, emit_source_claims,
)
from evigraph.services.ingest_source import IngestSink
from evigraph.services.scan import build_graph
from evigraph.services.repo_service import (
    CloneError, clone_repository, delete_repository, get_default_branch,
    get_head_commit_sha,
)
from evigraph.utils.hashing import (
    extract_git_host, generate_repo_id, normalize_github_url,
)

logger = logging.getLogger(__name__)


def run_ingestion(job_id: str, github_url: str, branch: Optional[str] = None,
                  github_token: Optional[str] = None, refresh: bool = False) -> None:
    """Run the full ingestion pipeline; job + lifecycle records track progress."""
    repo_id = ""
    cleared = False
    try:
        _job(job_id, "running", 5, "Validating repository")
        normalized_url, owner, repo_name = normalize_github_url(github_url)
        repo_id = generate_repo_id(owner, repo_name,
                                   extract_git_host(normalized_url))
        _job(job_id, "running", 5, "Validating repository", repo_id=repo_id)

        _job(job_id, "running", 10, "Cloning repository", repo_id=repo_id)
        _lifecycle(repo_id, "cloning")
        # Clone the normalized URL, not the caller's raw string: otherwise the
        # host we validated and the host we contact can differ.
        local_path = clone_repository(normalized_url, repo_id, branch,
                                      github_token)
        actual_branch = branch or get_default_branch(local_path)
        head_sha = get_head_commit_sha(local_path)

        _job(job_id, "running", 20, "Scanning files", repo_id=repo_id)
        scan_result = scan_repository(local_path)

        _job(job_id, "running", 30, "Parsing repository", repo_id=repo_id)
        _lifecycle(repo_id, "parsing")
        sink = build_graph(repo_id, owner, repo_name, normalized_url,
                            actual_branch, head_sha, scan_result)

        _job(job_id, "running", 60, "Resolving call graph", repo_id=repo_id)
        build_call_graph(repo_id, sink.parse_context, sink.nodes, sink.edges)

        if refresh:
            from evigraph.db.constraints import clear_repo_graph
            _job(job_id, "running", 70, "Clearing previous graph", repo_id=repo_id)
            cleared = True
            clear_repo_graph(repo_id)

        _job(job_id, "running", 75, "Writing graph to Neo4j", repo_id=repo_id)
        _lifecycle(repo_id, "writing")
        # `cleared` drives failed_partial vs failed_clean, so it flips only once
        # something has actually been mutated — not on entry to the write phase.
        nodes_written = graph_writer.write_nodes_batch(sink.nodes)
        cleared = True
        edges_written = graph_writer.write_edges_batch(sink.edges)

        _job(job_id, "running", 95, "Computing stats", repo_id=repo_id)
        graph_writer.update_repo_stats(repo_id)
        _stamp_coverage(repo_id, sink.coverage, sink.claims)
        _set_ingestion_status(repo_id, "completed")
        graph_writer.set_repo_lifecycle(repo_id, "ingested")

        _job(job_id, "completed", 100, "Ingestion completed successfully",
             repo_id=repo_id)
        logger.info("Ingestion complete for %s: %d nodes, %d edges (%s)",
                    repo_id, nodes_written, sum(edges_written.values()),
                    edges_written)

    except Exception as exc:
        state = "failed_partial" if cleared else "failed_clean"
        message = f"Ingestion failed ({state}): {exc}"
        logger.error("%s (job %s)", message, job_id)
        _job(job_id, "failed", 0, message, error=str(exc)[:500], repo_id=repo_id)
        if repo_id:
            _lifecycle(repo_id, state, error=str(exc)[:500])
            _set_ingestion_status(repo_id, "failed")


def _stamp_coverage(repo_id: str, coverage: dict, claims: dict | None = None) -> None:
    """Per-language parse coverage on the Repo node — losses stay visible (§8)."""
    claims = claims or {}
    # Every counter that represents a *loss* is totalled: a report that omits
    # skipped files reads as full coverage when it is not (design principle 7).
    #
    # The key set is taken from the data rather than listed here. A fixed list
    # silently dropped every counter added after it was written: a repository
    # whose thirteen routes were declined for computed paths recorded
    # `endpoints_computed_path` per language and still totalled to
    # `endpoints: 0` alone — the loss counted, then discarded one layer above
    # the reader. Anything numeric is a measurement; `tier` is the one label.
    keys = {key for entry in coverage.values() for key, value in entry.items()
            if isinstance(value, int) and not isinstance(value, bool)}
    totals = {key: sum(c.get(key, 0) for c in coverage.values())
              for key in sorted(keys)}
    totals["claims"] = sum(claims.values())
    # `.get` rather than indexing: with the key set taken from the data, a
    # repository that yielded no coverage at all has neither key, and the
    # summary for an empty scan must be zero rather than a KeyError.
    totals["files_unparsed"] = (totals.get("files_seen", 0)
                                - totals.get("files_parsed", 0))
    with get_session() as session:
        session.run(
            "MATCH (r:Repo {id: $repo_id}) "
            "SET r.parse_coverage = $coverage, r.parse_coverage_totals = $totals, "
            "    r.claims_by_kind = $claims",
            repo_id=repo_id, coverage=json.dumps(coverage),
            totals=json.dumps(totals), claims=json.dumps(claims),
        )


def _set_ingestion_status(repo_id: str, status: str) -> None:
    stamp = ", r.last_ingested_at = datetime()" if status == "completed" else ""
    with get_session() as session:
        session.run(
            f"MATCH (r:Repo {{id: $repo_id}}) SET r.ingestion_status = $status{stamp}",
            repo_id=repo_id, status=status,
        )


def _job(job_id: str, status: str, progress: int, message: str,
         error: Optional[str] = None, repo_id: str = "") -> None:
    graph_writer.create_or_update_job(job_id, repo_id, status, progress,
                                      message, error)


def _lifecycle(repo_id: str, state: str, error: str = "") -> None:
    """Best-effort lifecycle stamp; a first ingest has no Repo node yet."""
    try:
        graph_writer.set_repo_lifecycle(repo_id, state, error)
    except Exception as exc:
        logger.debug("Lifecycle stamp skipped for %s: %s", repo_id, exc)
