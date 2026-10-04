"""Deterministic bounded neighborhoods over an in-memory link result."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Neighborhood:
    distances: dict[str, int]
    walk_edges: list
    induced_edges: list
    total_neighbors: int
    total_induced_edges: int
    truncated: bool


def _edge_key(edge) -> tuple[str, str, str]:
    return edge.source_id, edge.type, edge.target_id


def bounded_neighborhood(edges: list, node_id: str, *, direction: str = "both",
                         depth: int = 1, edge_types: list[str] | None = None,
                         limit: int = 100) -> Neighborhood:
    """Walk asserted direction, then return bounded nodes and their edges."""
    if direction not in {"in", "out", "both"}:
        raise ValueError("direction must be in, out, or both")
    if not 1 <= int(depth) <= 8:
        raise ValueError("depth must be between 1 and 8")
    if not 1 <= int(limit) <= 500:
        raise ValueError("limit must be between 1 and 500")
    if edge_types is not None and (
            not isinstance(edge_types, list)
            or any(not isinstance(value, str) or not value for value in edge_types)):
        raise ValueError("edge_types must be a list of non-empty strings")
    allowed_types = set(edge_types or [])
    active = [edge for edge in edges
              if getattr(edge, "status", "active") == "active"
              and (not allowed_types or edge.type in allowed_types)]
    active.sort(key=_edge_key)

    adjacency: dict[str, list[tuple[str, object]]] = {}
    for edge in active:
        if direction in {"out", "both"}:
            adjacency.setdefault(edge.source_id, []).append((edge.target_id, edge))
        if direction in {"in", "both"}:
            adjacency.setdefault(edge.target_id, []).append((edge.source_id, edge))
    for values in adjacency.values():
        values.sort(key=lambda item: (item[0], _edge_key(item[1])))

    distances = {node_id: 0}
    walked: dict[tuple[str, str, str], object] = {}
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        distance = distances[current]
        if distance >= depth:
            continue
        for neighbor, edge in adjacency.get(current, []):
            walked[_edge_key(edge)] = edge
            if neighbor in distances:
                continue
            distances[neighbor] = distance + 1
            queue.append(neighbor)

    ordered = sorted((distance, candidate) for candidate, distance in distances.items()
                     if candidate != node_id)
    all_ids = set(distances)
    total_induced_edges = sum(
        edge.source_id in all_ids and edge.target_id in all_ids for edge in active)
    selected = ordered[:limit]
    selected_ids = {node_id, *(candidate for _, candidate in selected)}
    selected_distances = {node_id: 0, **{
        candidate: distance for distance, candidate in selected}}
    walk_edges = [edge for key, edge in sorted(walked.items())
                  if edge.source_id in selected_ids and edge.target_id in selected_ids]
    induced = [edge for edge in active
               if edge.source_id in selected_ids and edge.target_id in selected_ids]
    return Neighborhood(
        distances=selected_distances,
        walk_edges=walk_edges,
        induced_edges=induced,
        total_neighbors=len(ordered),
        total_induced_edges=total_induced_edges,
        truncated=len(ordered) > limit,
    )
