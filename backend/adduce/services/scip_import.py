"""Symbol-level CALLS from a SCIP index.

The 168-line name-resolution heuristic is this project's measured weak
point; a SCIP index is the compiler's own answer, produced per-language
by mature tooling and dropped in the repo root by CI. When `index.scip`
exists, its reference occurrences become CALLS edges FIRST, and the
heuristic resolver only fills pairs the index did not assert (the edge
dedupe key makes the precedence structural, not procedural).

Precision rules unchanged by the better source: an edge is emitted only
when BOTH symbols land on entities the scan actually parsed — matched by
file, containment, and name — so a stale index cannot mint edges into
functions that no longer exist. Every unmatched symbol is counted.
"""

from adduce.parsers.scip_parser import ScipDocument
from adduce.services.graph_factories import create_calls_edge

_FALLBACK_CONFIDENCE = 0.95


def _display_name(symbol: str) -> str:
    """`... module/Class#method().` -> `method`."""
    tail = symbol.rstrip(".").rstrip(")").rstrip("(")
    for sep in ("#", "/", ".", " "):
        tail = tail.rpartition(sep)[2]
    return tail


def _is_callable(symbol: str) -> bool:
    return symbol.endswith("().")


def scip_calls(documents: list[ScipDocument]) -> list[dict]:
    """(caller symbol, callee symbol, site) pairs, from occurrences alone.

    A reference's caller is the innermost DEFINITION whose enclosing
    range contains it; definitions without an enclosing range (older
    indexers) can enclose nothing and yield no callers.
    """
    calls = []
    for doc in documents:
        definitions = [o for o in doc.occurrences
                       if o.is_definition and _is_callable(o.symbol)
                       and len(o.enclosing) >= 3]
        for occ in doc.occurrences:
            if occ.is_definition or not _is_callable(occ.symbol):
                continue
            line = occ.range[0] if occ.range else -1
            enclosing = [d for d in definitions
                         if d.enclosing[0] <= line <= d.enclosing[-2]]
            if not enclosing:
                continue
            caller = min(enclosing,
                         key=lambda d: d.enclosing[-2] - d.enclosing[0])
            calls.append({"caller": caller, "callee": occ.symbol,
                          "path": doc.path, "line": line + 1})
    return calls


def _entity_index(parse_context: dict) -> dict:
    by_file: dict[str, list[dict]] = {}
    for path, ctx in parse_context.items():
        by_file[path] = [e for e in ctx.get("entities", [])
                         if e.get("start_line")]
    return by_file


def _locate(by_file: dict, path: str, line: int, name: str) -> dict | None:
    """The scanned entity a SCIP definition corresponds to, or None.

    File + line containment + name equality, innermost span on ties:
    all three must agree, because a stale index joined loosely would
    assert calls into functions that no longer exist.
    """
    candidates = [e for e in by_file.get(path, [])
                  if e["name"] == name
                  and e["start_line"] <= line <= (e.get("end_line")
                                                  or e["start_line"])]
    if not candidates:
        return None
    return min(candidates,
               key=lambda e: (e.get("end_line") or e["start_line"])
               - e["start_line"])


def import_scip_calls(repo_id: str, documents: list[ScipDocument],
                      parse_context: dict, nodes: list, edges: list,
                      sink, confidence: float | None = None) -> None:
    """Append CALLS edges the index asserts and the scan can anchor."""
    if confidence is None:
        confidence = _scip_confidence()
    by_file = _entity_index(parse_context)
    definitions: dict[str, dict | None] = {}
    for doc in documents:
        for occ in doc.occurrences:
            if occ.is_definition and _is_callable(occ.symbol):
                definitions[occ.symbol] = _locate(
                    by_file, doc.path, occ.line, _display_name(occ.symbol))

    node_ids = {n.id for n in nodes}
    edge_keys = {(e.source_id, e.target_id, e.type) for e in edges}
    for call in scip_calls(documents):
        caller = _locate(by_file, call["path"], call["caller"].line,
                         _display_name(call["caller"].symbol))
        callee = definitions.get(call["callee"])
        if caller is None or callee is None:
            sink.count_claim("_scip_unanchored")
            continue
        if caller["id"] not in node_ids or callee["id"] not in node_ids:
            sink.count_claim("_scip_unanchored")
            continue
        key = (caller["id"], callee["id"], "CALLS")
        if key in edge_keys:
            continue
        edge_keys.add(key)
        edge = create_calls_edge(repo_id, caller["id"], callee["id"],
                                 confidence,
                                 evidence=[f"{call['path']}:{call['line']}"])
        edge.detected_by = "scip_import"
        edge.match_type = "scip_reference"
        edges.append(edge)
        sink.count_claim("_scip_call")


def _scip_confidence() -> float:
    """The tier from config; a literal here would be invariant 7's bug."""
    from adduce.services.linker.base import load_confidence

    table = load_confidence().get("resolvers") or {}
    tier = (table.get("scip_import") or {}).get("reference") or {}
    return float(tier.get("confidence", _FALLBACK_CONFIDENCE))
