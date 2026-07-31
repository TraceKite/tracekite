"""The flat service map, assembled from stored rows.

This lived inside the `/api/v2/service-map` handler, which made it a fact
about the graph that only the server could state. Two of the decisions in
here are not response formatting at all:

- what KIND a node is, read from its labels — a Repo, a dead-end
  ServiceName, or a service
- which nodes exist at all, since an edge may reference a node the service
  query never returned

A library host drawing its own map had to reinvent both, and would have
disagreed with the app about what counts as a dead end. That is the drift
the "server may orchestrate, it may not compute" rule exists to stop, so
the rule now has one implementation and both surfaces call it.

Pure: rows in, response out. The queries, their limits and the session
stay in the route, because deciding what to fetch is orchestration.
"""


def node_kind(labels: list) -> str:
    """A node's kind, from its stored labels.

    `ServiceName` means a name nothing resolved to — a dead end, and worth
    drawing as one rather than hiding, because an unresolved name is a
    visible recall gap.
    """
    if "Repo" in (labels or []):
        return "repo"
    if "ServiceName" in (labels or []):
        return "service_name"
    return "node"


def assemble_service_map(node_rows: list, edge_rows: list,
                         total_edges: int) -> dict:
    """Nodes and edges for the flat map, plus honest totals.

    `total_edges` is counted separately by the caller and passed in: paging
    the edge query and then reporting the page size as the total is how a
    truncated map claims to be the whole estate.
    """
    nodes: dict[str, dict] = {}
    for row in node_rows:
        nodes[row["id"]] = {
            "id": row["id"], "name": row["name"], "kind": "service",
            "is_gateway": bool(row.get("is_gateway")),
            "repo_ids": row.get("repo_ids") or [],
        }

    edges = []
    for row in edge_rows:
        for side in ("source", "target"):
            node_id = row[side]
            if node_id in nodes:
                continue
            kind = node_kind(row.get(f"{side}_labels"))
            nodes[node_id] = {"id": node_id, "name": row[f"{side}_name"],
                              "kind": kind,
                              "dead_end": kind == "service_name",
                              "scope": row.get(f"{side}_scope")}
        edges.append({
            "source": row["source"], "target": row["target"],
            "type": row["type"], "confidence": row.get("confidence"),
            "min_confidence": row.get("min_confidence"),
            "max_confidence": row.get("max_confidence"),
            "via": row.get("via") or [], "weight": row.get("weight"),
            "path_prefix": row.get("path_prefix"),
            "source_repo_id": row.get("source_repo_id") or "",
            "evidence": (row.get("evidence") or [])[:3],
        })

    return {"nodes": list(nodes.values()), "edges": edges,
            "totals": {"services": len(node_rows), "edges": total_edges},
            "truncated": total_edges > len(edges)}
