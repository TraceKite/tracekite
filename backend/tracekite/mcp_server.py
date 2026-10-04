"""An MCP server over the library: agents query the graph.

Implements the MCP stdio transport directly — newline-delimited JSON-RPC
with `initialize`, `tools/list` and `tools/call` — rather than adopting an
SDK: `pip install tracekite-core` promises a light dependency set, and three
methods over stdin do not justify a framework. The server completes its
handshake before loading artifacts, then links them in memory on the first
valid tool call; every later tool answers from that one result.

Errors are JSON-RPC errors, never crashes: an agent sending a malformed
frame gets told so and the loop continues — a server that dies on the
first bad message punishes the wrong party.
"""

import json
import logging
import sys

from tracekite.answer import CONFIG_VERSION, ENGINE_VERSION, SnapshotIdentity
from tracekite.facade import collect_claims as _collect_claims
from tracekite.mcp_envelope import wrap_answer
from tracekite.mcp_tools import GraphTools
from tracekite.scan_meta import ScanMeta, repo_scan_meta_from_sink
from tracekite.source_meta import collect_input_meta

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "services",
     "description": "Every service backed by a scanned repository.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "node",
     "description": "Describe one exact graph node id.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {"node_id": {"type": "string"}}}},
    {"name": "search",
     "description": "Find graph node ids by name, label, path, or id.",
     "inputSchema": {"type": "object", "required": ["query"],
                     "properties": {
                         "query": {"type": "string", "minLength": 1},
                         "limit": {"type": "integer", "minimum": 1,
                                   "maximum": 100}}}},
    {"name": "consumers_of",
     "description": "Who depends on this node id, with file:line evidence citations across repositories.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {"node_id": {"type": "string"}}}},
    {"name": "trace",
     "description": "Up to 3 shortest active call paths between two node ids.",
     "inputSchema": {"type": "object",
                     "required": ["from_id", "to_id"],
                     "properties": {"from_id": {"type": "string"},
                                     "to_id": {"type": "string"},
                                    "max_hops": {"type": "integer",
                                                 "minimum": 1,
                                                 "maximum": 8}}}},
    {"name": "neighbors",
     "description": "Bounded adjacent nodes and evidence-rich edges in asserted direction.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {
                         "node_id": {"type": "string"},
                         "direction": {"enum": ["in", "out", "both"]},
                         "depth": {"type": "integer", "minimum": 1,
                                   "maximum": 8},
                         "edge_types": {"type": "array",
                                        "items": {"type": "string"}},
                         "limit": {"type": "integer", "minimum": 1,
                                   "maximum": 500}}}},
    {"name": "impact",
     "description": "Transitive dependents with evidence paths and path confidence.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {
                         "node_id": {"type": "string"},
                         "depth": {"type": "integer", "minimum": 1,
                                   "maximum": 8},
                         "limit": {"type": "integer", "minimum": 1,
                                   "maximum": 500},
                         "min_confidence": {"type": "number", "minimum": 0,
                                            "maximum": 1},
                         "edge_types": {"type": "array",
                                        "items": {"type": "string"}}}}},
    {"name": "subgraph",
     "description": "A bounded ego graph with described nodes and induced edges.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {
                         "node_id": {"type": "string"},
                         "direction": {"enum": ["in", "out", "both"]},
                         "depth": {"type": "integer", "minimum": 1,
                                   "maximum": 8},
                         "edge_types": {"type": "array",
                                        "items": {"type": "string"}},
                         "node_limit": {"type": "integer", "minimum": 2,
                                        "maximum": 500},
                         "edge_limit": {"type": "integer", "minimum": 1,
                                        "maximum": 1000}}}},
    {"name": "deprecations",
     "description": "Deprecated contracts and their live consumers.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _response(request_id, result=None, error=None) -> dict:
    if error is not None:
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle(message: object, tools: GraphTools | None) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(message, dict):
        return _response(None, error={
            "code": -32600, "message": "invalid request"})
    method = message.get("method", "")
    request_id = message.get("id")
    if request_id is None:
        return None                       # notification: nothing to say
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "tracekite", "version": "1"}})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            return _response(request_id, error={
                "code": -32602, "message": "params must be an object"})
        name = params.get("name", "")
        if name not in {t["name"] for t in TOOLS}:
            return _response(request_id, error={
                "code": -32602, "message": f"unknown tool {name!r}"})
        if tools is None:
            return _response(request_id, error={
                "code": -32603, "message": "graph is not loaded"})
        handler = getattr(tools, name)
        try:
            answer = handler(**(params.get("arguments") or {}))
        except (TypeError, ValueError) as exc:
            return _response(request_id, error={
                "code": -32602, "message": str(exc)})
        if tools._snapshot is not None:
            answer = wrap_answer(answer, name, params.get("arguments") or {},
                                 tools._snapshot,
                                 known_ids=tools._known_node_ids(),
                                 scan_meta=tools._scan_meta,
                                 expected_repos=[
                                     revision.repo_id
                                     for revision in tools._snapshot.repos
                                 ])
        return _response(request_id, {
            "content": [{"type": "text",
                         "text": json.dumps(answer, sort_keys=True)}]})
    return _response(request_id, error={
        "code": -32601, "message": f"unknown method {method!r}"})


def _load_tools(paths: list[str]) -> GraphTools:
    """Scan or load each input once, when the first graph query arrives."""
    from tracekite import engine_config
    from tracekite.db.artifact_node_lookup import node_lookup_for_inputs
    from tracekite.scan_meta import config_digest
    from tracekite.services.linker.engine import link

    claims: list = []
    commits: dict = {}
    revisions, scan_meta = collect_input_meta(paths)
    sinks: dict = {}
    cfg = engine_config.get_config()
    for path in paths:
        _collect_claims(path, claims, commits, sinks=sinks)
    for repo_id, sink in sinks.items():
        scan_meta.add(repo_scan_meta_from_sink(
            sink, repo_id, budgets={
                "files": cfg.max_files_per_repo,
                "claims": cfg.max_claims_per_repo,
            }))
    result = link(claims, run_id="linkrun_mcp",
                  now="2026-01-01T00:00:00+00:00")
    snapshot = SnapshotIdentity(
        repos=revisions, engine_version=ENGINE_VERSION,
        config_version=CONFIG_VERSION,
        config_digest=config_digest(cfg))
    return GraphTools(
        result, commits=commits, snapshot=snapshot, scan_meta=scan_meta,
        node_lookup=node_lookup_for_inputs(paths, sinks))


def _valid_tool_call(message: object) -> bool:
    if not isinstance(message, dict) or message.get("id") is None:
        return False
    params = message.get("params")
    return (message.get("method") == "tools/call"
            and isinstance(params, dict)
            and params.get("name") in {tool["name"] for tool in TOOLS})


def serve(paths: list[str] | None = None, stdin=None, stdout=None) -> int:
    """Answer the handshake immediately; load the graph on first tool use."""
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr, force=True)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    paths = paths or ["."]
    graph_tools = None

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps(_response(None, error={
                "code": -32700, "message": "parse error"})), file=stdout,
                flush=True)
            continue
        if graph_tools is None and _valid_tool_call(message):
            try:
                graph_tools = _load_tools(paths)
            except Exception as exc:
                logger.exception("failed to load MCP graph")
                reply = _response(message["id"], error={
                    "code": -32603,
                    "message": f"graph load failed: {type(exc).__name__}",
                })
                print(json.dumps(reply, sort_keys=True), file=stdout,
                      flush=True)
                continue
        reply = handle(message, graph_tools)
        if reply is not None:
            print(json.dumps(reply, sort_keys=True), file=stdout, flush=True)
    return 0
