"""An MCP server over the library: agents query the graph.

Implements the MCP stdio transport directly — newline-delimited JSON-RPC
with `initialize`, `tools/list` and `tools/call` — rather than adopting an
SDK: `pip install adduce-core` promises a light dependency set, and three
methods over stdin do not justify a framework. The server loads artifacts
once at startup and links them in memory; every tool answers from that one
result, so an agent's ten questions cost one link.

Errors are JSON-RPC errors, never crashes: an agent sending a malformed
frame gets told so and the loop continues — a server that dies on the
first bad message punishes the wrong party.
"""

import json
import logging
import sys

from adduce.utils.evidence import as_spans

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {"name": "services",
     "description": "Every service in the estate, with its repositories.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "consumers_of",
     "description": "Who depends on this node id, with file:line evidence.",
     "inputSchema": {"type": "object", "required": ["node_id"],
                     "properties": {"node_id": {"type": "string"}}}},
    {"name": "trace",
     "description": "Up to 3 shortest active paths between two node ids.",
     "inputSchema": {"type": "object",
                     "required": ["from_id", "to_id"],
                     "properties": {"from_id": {"type": "string"},
                                    "to_id": {"type": "string"},
                                    "max_hops": {"type": "integer"}}}},
    {"name": "deprecations",
     "description": "Deprecated contracts and their live consumers.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class GraphTools:
    """The four questions, answered from one in-memory link result."""

    def __init__(self, result, commits: dict | None = None):
        self._result = result
        # repo_id -> head_sha from each artifact's own meta. Spans carry no
        # per-string commit because edge evidence merges both sides and
        # guessing which repo a path belongs to would be invented
        # attribution; agents join file paths against this map themselves.
        self._commits = commits or {}

    def services(self) -> dict:
        return {"services": [
            {"id": s.service_id, "name": s.name,
             "repos": sorted(s.repo_ids or [])}
            for s in sorted(self._result.services,
                            key=lambda s: s.service_id)],
            "commits": dict(sorted(self._commits.items()))}

    def consumers_of(self, node_id: str) -> dict:
        consumers = [
            {"consumer": e.source_id, "type": e.type,
             "confidence": round(e.confidence, 4),
             "evidence": list(e.evidence or []),
             "spans": as_spans(e.evidence)}
            for e in self._result.edges
            if e.target_id == node_id and e.status == "active"]
        # found=False with candidates, never an empty list for an unknown
        # id: "nobody depends on it" is the one wrong answer to hand
        # someone deciding whether a removal is safe.
        if not consumers:
            known = {e.target_id for e in self._result.edges
                     if e.status == "active"}
            if node_id not in known:
                return {"found": False, "node_id": node_id,
                        "candidates": sorted(known)[:25]}
        return {"found": True, "node_id": node_id, "consumers": consumers}

    def trace(self, from_id: str, to_id: str, max_hops: int = 6) -> dict:
        from adduce.services.linker.traverse import find_paths

        paths = find_paths(self._result.edges, from_id, to_id,
                           max_hops=min(int(max_hops), 8))
        return {"from": from_id, "to": to_id, "paths": paths,
                "found": bool(paths)}

    def deprecations(self) -> dict:
        from adduce.services.linker.deprecations import deprecation_report

        return {"contracts": deprecation_report(
            self._result.edges, self._result.rendezvous)}


def _response(request_id, result=None, error=None) -> dict:
    if error is not None:
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle(message: dict, tools: GraphTools) -> dict | None:
    """One JSON-RPC message in, one response out (None for notifications)."""
    method = message.get("method", "")
    request_id = message.get("id")
    if request_id is None:
        return None                       # notification: nothing to say
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "adduce", "version": "1"}})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        handler = getattr(tools, name, None)
        if name not in {t["name"] for t in TOOLS} or handler is None:
            return _response(request_id, error={
                "code": -32602, "message": f"unknown tool {name!r}"})
        try:
            answer = handler(**(params.get("arguments") or {}))
        except TypeError as exc:
            return _response(request_id, error={
                "code": -32602, "message": str(exc)})
        return _response(request_id, {
            "content": [{"type": "text",
                         "text": json.dumps(answer, sort_keys=True)}]})
    return _response(request_id, error={
        "code": -32601, "message": f"unknown method {method!r}"})


def serve(artifact_paths: list[str], stdin=None, stdout=None) -> int:
    """Load, link once, answer until EOF."""
    from adduce.db.artifact import read_meta
    from adduce.db.artifact_reader import read_claims
    from adduce.services.linker.engine import link

    claims = [c for p in artifact_paths for c in read_claims(p)]
    result = link(claims, run_id="linkrun_mcp",
                  now="2026-01-01T00:00:00+00:00")
    commits = {}
    for path in artifact_paths:
        meta = read_meta(path)
        if meta.get("repo_id"):
            commits[meta["repo_id"]] = meta.get("head_sha", "")
    tools = GraphTools(result, commits)

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
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
        reply = handle(message, tools)
        if reply is not None:
            print(json.dumps(reply, sort_keys=True), file=stdout, flush=True)
    return 0
