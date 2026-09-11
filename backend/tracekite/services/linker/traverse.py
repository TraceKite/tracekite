"""Bounded path search over a link result's edges.

The store backends answer path queries in SQL and Cypher; a library host
holding a `LinkResult` in memory has no store to ask. This is the same
question answered over the in-memory shape — bounded, served-edges-only,
and deterministic, because two agents asking the same question must see
the same paths in the same order.
"""

from collections import deque


def find_paths(edges: list, source: str, target: str, *,
               max_hops: int = 6, limit: int = 3) -> list[list[dict]]:
    """Up to `limit` shortest active-edge paths from source to target.

    Breadth-first, so shorter paths always precede longer ones; neighbour
    order is sorted so the answer cannot depend on edge insertion order.
    Candidate edges never carry a path — a route through an assertion the
    tool declined to serve would smuggle it back in.
    """
    adjacency: dict[str, list] = {}
    for edge in edges:
        if getattr(edge, "status", "active") != "active":
            continue
        adjacency.setdefault(edge.source_id, []).append(edge)
    for neighbours in adjacency.values():
        neighbours.sort(key=lambda e: (e.target_id, e.type))

    found: list[list[dict]] = []
    queue = deque([(source, [])])
    while queue and len(found) < limit:
        node, path = queue.popleft()
        if len(path) >= max_hops and node != target:
            continue
        if node == target and path:
            found.append([{
                "source": e.source_id, "target": e.target_id,
                "type": e.type, "confidence": round(e.confidence, 4),
                "evidence": list(e.evidence or [])} for e in path])
            continue
        seen_on_path = {e.source_id for e in path} | {node}
        for edge in adjacency.get(node, []):
            if edge.target_id in seen_on_path:
                continue
            queue.append((edge.target_id, path + [edge]))
    return found
