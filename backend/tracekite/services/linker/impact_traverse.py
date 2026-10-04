"""Transitive dependents over the in-memory linker graph."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from itertools import count

from tracekite.services.linker.confidence_math import path_confidence
from tracekite.services.linker.dependence import is_dependence
from tracekite.services.linker.edge_view import edge_record


@dataclass(frozen=True)
class ImpactTraversal:
    impacted: list[dict]
    total_impacted: int
    truncated: bool


def _interval(edge) -> tuple[float, float, float]:
    point = float(getattr(edge, "confidence", 0.0) or 0.0)
    extra = dict(getattr(edge, "extra_props", {}) or {})
    low = extra.get("min_confidence")
    high = extra.get("max_confidence")
    return point, point if low is None else float(low), \
        point if high is None else float(high)


def transitive_impact(edges: list, node_id: str, *, depth: int = 6,
                      limit: int = 100, min_confidence: float = 0.0,
                      edge_types: list[str] | None = None) -> ImpactTraversal:
    """Shortest dependent paths, strongest path first when lengths tie."""
    if not 1 <= int(depth) <= 8:
        raise ValueError("depth must be between 1 and 8")
    if not 1 <= int(limit) <= 500:
        raise ValueError("limit must be between 1 and 500")
    minimum = float(min_confidence)
    if not 0.0 <= minimum <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    if edge_types is not None and (
            not isinstance(edge_types, list)
            or any(not isinstance(value, str) or not value for value in edge_types)):
        raise ValueError("edge_types must be a list of non-empty strings")
    allowed = set(edge_types or [])
    incoming: dict[str, list] = {}
    for edge in edges:
        if (getattr(edge, "status", "active") != "active"
                or not is_dependence(edge)
                or (allowed and edge.type not in allowed)
                or float(getattr(edge, "confidence", 0.0) or 0.0) < minimum):
            continue
        incoming.setdefault(edge.target_id, []).append(edge)
    for values in incoming.values():
        values.sort(key=lambda edge: (edge.source_id, edge.type, edge.target_id))

    serial = count()
    queue = [(0, -1.0, node_id, next(serial), [], (node_id,))]
    best: dict[str, tuple[int, float, list]] = {node_id: (0, 1.0, [])}
    while queue:
        hops, neg_product, current, _serial, path, seen = heapq.heappop(queue)
        product = -neg_product
        known = best.get(current)
        if known is None or hops != known[0] or product < known[1]:
            continue
        if hops >= depth:
            continue
        for edge in incoming.get(current, []):
            dependent = edge.source_id
            if dependent in seen:
                continue
            candidate_hops = hops + 1
            candidate_product = product * float(edge.confidence)
            previous = best.get(dependent)
            if previous is not None and (
                    previous[0] < candidate_hops
                    or (previous[0] == candidate_hops
                        and previous[1] >= candidate_product)):
                continue
            candidate_path = path + [edge]
            best[dependent] = (candidate_hops, candidate_product, candidate_path)
            heapq.heappush(queue, (
                candidate_hops, -candidate_product, dependent, next(serial),
                candidate_path, (*seen, dependent)))

    rows = []
    for dependent, (hops, _product, path) in best.items():
        if dependent == node_id:
            continue
        records = []
        for edge in path:
            records.append({**edge_record(edge),
                            "impact_from": edge.target_id,
                            "impact_to": edge.source_id})
        rows.append({"node_id": dependent, "distance": hops,
                     "confidence": path_confidence([_interval(edge) for edge in path]),
                     "path": records})
    rows.sort(key=lambda row: (
        row["distance"], -row["confidence"]["compounded"], row["node_id"]))
    return ImpactTraversal(rows[:limit], len(rows), len(rows) > limit)
