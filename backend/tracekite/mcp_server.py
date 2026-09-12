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
from tracekite.scan_meta import (
    ScanMeta,
    repo_scan_meta_from_sink,
)
from tracekite.source_meta import collect_input_meta
from tracekite.utils import rendezvous_ids as rid
from tracekite.utils.evidence import as_spans

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "services",
     "description": "Every service backed by a scanned repository.",
     "inputSchema": {"type": "object", "properties": {}}},
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
    {"name": "deprecations",
     "description": "Deprecated contracts and their live consumers.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class GraphTools:
    """The four questions, answered from one in-memory link result."""

    def __init__(self, result, commits: dict | None = None,
                 snapshot: SnapshotIdentity | None = None,
                 scan_meta: ScanMeta | None = None):
        self._result = result
        # repo_id -> head_sha from each artifact's own meta. Spans carry no
        # per-string commit because edge evidence merges both sides and
        # guessing which repo a path belongs to would be invented
        # attribution; agents join file paths against this map themselves.
        self._commits = commits or {}
        self._snapshot = snapshot
        self._scan_meta = scan_meta

    def _known_node_ids(self) -> set[str]:
        active = {
            node_id
            for edge in self._result.edges if edge.status == "active"
            for node_id in (edge.source_id, edge.target_id)
        }
        backed_services = {
            service.service_id for service in self._result.services
            if service.repo_ids
        }
        return active | backed_services

    def _resolve_node_id(self, query: str) -> tuple[str | None, list[str]]:
        """Resolve one unambiguous service name or exact known node ID."""
        if not isinstance(query, str):
            raise ValueError("node id must be a string")
        if not query:
            return query, []
        known_ids = self._known_node_ids()
        if query in known_ids:
            return query, []

        candidates = set()
        for s in self._result.services:
            if query != s.service_id and query.lower() != s.name.lower():
                continue
            candidates.update(candidate for candidate in (
                s.service_id, rid.service_id(s.name)) if candidate in known_ids)
        ordered = sorted(candidates)
        if len(ordered) == 1:
            return ordered[0], []
        if len(ordered) > 1:
            return None, ordered
        return query, []

    def services(self) -> dict:
        return {"services": [
            {"id": s.service_id, "name": s.name,
             "repos": sorted(s.repo_ids or [])}
            for s in sorted(self._result.services,
                            key=lambda s: s.service_id)
            if s.repo_ids],
            "commits": dict(sorted(self._commits.items()))}

    def consumers_of(self, node_id: str) -> dict:
        target, ambiguous = self._resolve_node_id(node_id)
        if ambiguous:
            return {"found": False, "node_id": node_id,
                    "reason": "ambiguous service name",
                    "candidates": ambiguous}
        consumers = [
            {"consumer": e.source_id, "type": e.type,
             "confidence": round(e.confidence, 4),
             "evidence": list(e.evidence or []),
             "spans": as_spans(e.evidence)}
            for e in self._result.edges
            if e.target_id == target and e.status == "active"]
        if not consumers:
            known = self._known_node_ids()
            if target not in known:
                friendly_candidates = sorted([
                    f"{s.name} ({s.service_id})" for s in self._result.services
                    if s.repo_ids
                ] or list(known))[:25]
                return {"found": False, "node_id": node_id,
                        "candidates": friendly_candidates}
        return {"found": True, "node_id": target, "consumers": consumers}

    def trace(self, from_id: str, to_id: str, max_hops: int = 6) -> dict:
        from tracekite.services.linker.traverse import find_paths

        src, from_candidates = self._resolve_node_id(from_id)
        dst, to_candidates = self._resolve_node_id(to_id)
        if from_candidates or to_candidates:
            return {"from": from_id, "to": to_id, "paths": [],
                    "found": False, "reason": "ambiguous service name",
                    "candidates": {"from": from_candidates,
                                   "to": to_candidates}}
        hops = int(max_hops)
        if not 1 <= hops <= 8:
            raise ValueError("max_hops must be between 1 and 8")
        paths = find_paths(self._result.edges, src, dst, max_hops=hops)
        return {"from": from_id, "to": to_id,
                "resolved_from": src, "resolved_to": dst, "paths": paths,
                "found": bool(paths)}

    def deprecations(self) -> dict:
        from tracekite.services.linker.deprecations import deprecation_report

        return {"contracts": deprecation_report(
            self._result.edges, self._result.rendezvous)}


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
    return GraphTools(result, commits=commits, snapshot=snapshot,
                      scan_meta=scan_meta)


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
