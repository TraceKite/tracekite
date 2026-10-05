"""One file into the sink: read it, parse it within budget, emit what it yields.

The serial scan and every sharded worker run this same loop, so it is the one
place where a failure can say which file caused it.
"""

import logging

from tracekite.engine_config import get_config
from tracekite.parsers.parser_registry import get_parser_for_file
from tracekite.parsers.tree_sitter.adapter import TreeSitterSourceParser
from tracekite.services.ingest_artifacts import (
    process_agent_card, process_asyncapi, process_avro, process_buf,
    process_catalog, process_codeowners, process_config, process_dependencies,
    process_docker, process_gateway, process_graphql, process_iac,
    process_k8s, process_mcp_config, process_migration, process_observability,
    process_cron, process_iac_units, process_openapi,
    process_pipeline, process_proto, process_publish,
)
from tracekite.services.ingest_claims import (
    emit_mcp_manifest_claims, emit_source_claims,
)
from tracekite.services.ingest_source import IngestSink, process_source_file
from tracekite.services.parse_budget import ParseTimeout, parse_within_budget

logger = logging.getLogger(__name__)


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
        try:
            _parse_one_file(repo_id, file_info, file_ids[file_info.path], sink)
        except Exception as exc:
            # Still fatal, and still the same exception — callers rely on its
            # type, e.g. RedactionKeyMissing failing closed — but it now says
            # which file raised it. strapi's whole ingest failed with only
            # "'NoneType' object has no attribute 'startswith'".
            exc.add_note(f"while scanning {file_info.path}")
            raise


def _record_specialized_parse(file_info, result: dict,
                              sink: IngestSink) -> None:
    """Count a file parsed by a manifest or contract parser.

    Source coverage and structured-file coverage share the same file total.
    A protobuf, Terraform, or Avro file has no source AST, but calling it
    unsupported after its dedicated parser emitted claims makes absence and
    every MCP completeness envelope contradict the graph.
    """
    parsed = any(
        value is not None
        for name, value in result.items()
        if name != "source_result"
    )
    if not parsed:
        return
    counters = sink.lang(file_info.language)
    counters["files_parsed"] += 1
    sink.upgrade_tier(file_info.language, "lite")


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
        result = parse_within_budget(file_info.path, content)
    except ParseTimeout:
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

    if source is None or source.errors:
        _record_specialized_parse(file_info, result, sink)

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
