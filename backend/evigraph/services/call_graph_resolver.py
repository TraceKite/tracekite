"""
Build symbol-level CALLS edges from Tree-sitter method-call extractions.

Resolution is intentionally conservative: edges are only emitted when the
symbol can be located in the parsed codebase. Confidence reflects the strength
of the resolution heuristic.
"""

import logging
from typing import Optional

from evigraph.services.graph_factories import create_calls_edge

# Provisional, uncalibrated resolution confidences (config/confidence.yml, §7):
# kept below trace defaults until the calibration harness measures them.
CONFIDENCE_UNIQUE_MATCH = 0.9
CONFIDENCE_AMBIGUOUS_MATCH = 0.7

logger = logging.getLogger(__name__)

# Common library/runtime prefixes that should not generate call-graph edges.
_IGNORED_PREFIXES = {
    "print", "len", "range", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "map", "filter", "reduce", "sum", "min", "max", "abs", "round",
    "logger", "log", "console", "system", "math", "json", "os", "sys", "re",
    "time", "datetime", "random", "string", "collections", "itertools",
}


def build_call_graph(
    repo_id: str,
    parse_context: dict[str, dict],
    nodes: list,
    edges: list,
):
    """Resolve method calls and append CALLS edges to the graph."""
    node_ids = {n.id for n in nodes}
    edge_keys = {(e.source_id, e.target_id, e.type) for e in edges}

    symbol_records: list[dict] = []
    by_file_qualified: dict[tuple[str, str], list[dict]] = {}
    by_file_name: dict[tuple[str, str], list[dict]] = {}
    by_class_method: dict[tuple[str, str], list[dict]] = {}

    for file_path, ctx in parse_context.items():
        for rec in ctx.get("entities", []):
            symbol_records.append(rec)
            key = (file_path, rec["qualified_name"])
            by_file_qualified.setdefault(key, []).append(rec)
            by_file_name.setdefault((file_path, rec["name"]), []).append(rec)
            if rec.get("parent_class"):
                by_class_method.setdefault((rec["parent_class"], rec["name"]), []).append(rec)

    for file_path, ctx in parse_context.items():
        file_node_id = ctx["file_node_id"]
        for call in ctx.get("method_calls", []):
            caller = _resolve_caller(file_path, call.line, symbol_records)
            if caller is None:
                continue

            caller_id = caller["id"]
            if caller_id not in node_ids:
                continue

            callee_id, confidence = _resolve_callee(
                file_path,
                call.callee_name,
                caller,
                by_file_qualified,
                by_file_name,
                by_class_method,
            )

            if callee_id is None:
                # Skip library/runtime calls instead of creating noise.
                if _is_ignored_call(call.callee_name):
                    continue
                continue

            if callee_id not in node_ids:
                continue

            key = (caller_id, callee_id, "CALLS")
            if key in edge_keys:
                continue
            edge_keys.add(key)

            edges.append(
                create_calls_edge(
                    repo_id, caller_id, callee_id, confidence,
                    evidence=[f"{file_path}:{call.line}"],
                )
            )


def _resolve_caller(file_path: str, line: int, symbol_records: list[dict]) -> Optional[dict]:
    """Find the symbol whose body contains the call site."""
    candidates = [
        rec
        for rec in symbol_records
        if rec["file_path"] == file_path
        and rec["type"] in ("method", "function")
        and rec["start_line"] <= line <= rec["end_line"]
    ]
    if not candidates:
        return None
    # Prefer the smallest enclosing symbol (innermost scope).
    candidates.sort(key=lambda r: r["end_line"] - r["start_line"])
    return candidates[0]


def _resolve_callee(
    file_path: str,
    callee_name: str,
    caller: dict,
    by_file_qualified: dict[tuple[str, str], list[dict]],
    by_file_name: dict[tuple[str, str], list[dict]],
    by_class_method: dict[tuple[str, str], list[dict]],
) -> tuple[Optional[str], float]:
    """Resolve a callee name to a symbol ID and confidence."""
    if not callee_name:
        return None, 0.0

    callee_name = callee_name.strip()
    parts = callee_name.split(".")
    base = parts[-1]
    prefix = parts[0] if len(parts) > 1 else None

    # Strip common self-references.
    if prefix in ("this", "self", "cls"):
        prefix = None

    # 1. Same-class method call: Foo.bar where Foo is the caller's class.
    if prefix is None and caller.get("parent_class"):
        recs = by_class_method.get((caller["parent_class"], base), [])
        if len(recs) == 1:
            return recs[0]["id"], CONFIDENCE_UNIQUE_MATCH

    # 2. Same-file top-level function or method by name.
    if prefix is None:
        recs = by_file_name.get((file_path, base), [])
        if len(recs) == 1:
            return recs[0]["id"], CONFIDENCE_UNIQUE_MATCH
        if len(recs) > 1:
            # Ambiguous: pick the one closest to the caller.
            best = min(recs, key=lambda r: abs(r["start_line"] - caller["start_line"]))
            return best["id"], CONFIDENCE_AMBIGUOUS_MATCH

    # 3. Cross-file class.method call.
    if prefix is not None:
        recs = by_class_method.get((prefix, base), [])
        if len(recs) == 1:
            return recs[0]["id"], CONFIDENCE_AMBIGUOUS_MATCH
        if len(recs) > 1:
            best = min(recs, key=lambda r: abs(r["start_line"] - caller["start_line"]))
            return best["id"], CONFIDENCE_AMBIGUOUS_MATCH

    return None, 0.0


def _is_ignored_call(callee_name: str) -> bool:
    """Return True for calls that are clearly standard library/runtime."""
    if not callee_name:
        return True
    parts = callee_name.split(".")
    return parts[0].lower() in _IGNORED_PREFIXES
