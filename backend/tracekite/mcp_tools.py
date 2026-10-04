"""In-memory graph questions shared by MCP and the framework facade."""

from __future__ import annotations

from tracekite.answer import SnapshotIdentity
from tracekite.node_lookup import EmptyNodeLookup, NodeLookup, search_rank
from tracekite.scan_meta import ScanMeta
from tracekite.services.linker.dependence import is_dependence
from tracekite.services.linker.edge_view import edge_record
from tracekite.services.linker.neighborhood import bounded_neighborhood
from tracekite.utils import rendezvous_ids as rid


def _linked_node_records(result) -> dict[str, dict]:
    records = {}
    for service in result.services:
        if not service.repo_ids:
            continue
        records[service.service_id] = {
            "id": service.service_id, "type": "Service", "name": service.name,
            "label": service.name, "repo_id": "", "path": None,
            "repos": sorted(service.repo_ids),
            "is_gateway": bool(getattr(service, "is_gateway", False)),
        }
    for spec in result.rendezvous:
        props = dict(spec.props or {})
        name = str(props.get("name") or props.get("path_template")
                   or props.get("key") or spec.node_id)
        records[spec.node_id] = {
            "id": spec.node_id, "type": spec.label, "name": name,
            "label": name, "repo_id": "", "path": None,
            "properties": props,
        }
    for edge in result.edges:
        if getattr(edge, "status", "active") != "active":
            continue
        records.setdefault(edge.source_id, {
            "id": edge.source_id,
            "type": str(getattr(edge, "source_label", "") or ""),
            "name": edge.source_id, "label": edge.source_id,
            "repo_id": str(getattr(edge, "source_repo_id", "") or ""),
            "path": None})
        records.setdefault(edge.target_id, {
            "id": edge.target_id,
            "type": str(getattr(edge, "target_label", "") or ""),
            "name": edge.target_id, "label": edge.target_id,
            "repo_id": str(getattr(edge, "target_repo_id", "") or ""),
            "path": None})
    return records


class GraphTools:
    """Evidence-backed graph queries over one immutable link result."""

    def __init__(self, result, commits: dict | None = None,
                 snapshot: SnapshotIdentity | None = None,
                 scan_meta: ScanMeta | None = None,
                 node_lookup: NodeLookup | None = None):
        self._result = result
        self._commits = commits or {}
        self._snapshot = snapshot
        self._scan_meta = scan_meta
        self._node_lookup = node_lookup or EmptyNodeLookup()
        self._node_cache: dict[str, dict | None] = {}
        self._linked_nodes = _linked_node_records(result)

    def _known_node_ids(self) -> set[str]:
        return set(self._linked_nodes)

    def _resolve_node_id(self, query: str) -> tuple[str | None, list[str]]:
        """Resolve one unambiguous service name or exact known node ID."""
        if not isinstance(query, str):
            raise ValueError("node id must be a string")
        if not query:
            return query, []
        known_ids = self._known_node_ids()
        exact = query in known_ids or self._source_node(query) is not None
        named = set()
        for service in self._result.services:
            if query != service.service_id and query.casefold() not in {
                    service.name.casefold(),
                    service.name.casefold().rpartition("/")[2]}:
                continue
            named.update(candidate for candidate in (
                service.service_id, rid.service_id(service.name))
                if candidate in known_ids)
        if exact:
            if named - {query}:
                return None, sorted({query} | named)
            return query, []
        ordered = sorted(named)
        if len(ordered) == 1:
            return ordered[0], []
        if len(ordered) > 1:
            return None, ordered
        return query, []

    def _source_node(self, node_id: str) -> dict | None:
        if node_id not in self._node_cache:
            self._node_cache[node_id] = self._node_lookup.get(node_id)
        return self._node_cache[node_id]

    def _linked_node(self, node_id: str) -> dict | None:
        return self._linked_nodes.get(node_id)

    def _describe(self, node_id: str) -> dict | None:
        # A scan node carries name/path/line identity; an edge endpoint carries
        # only labels and repository attribution. Prefer the richer exact node.
        return self._source_node(node_id) or self._linked_node(node_id)

    def _unknown(self, query: str) -> dict:
        candidates = sorted(
            f"{service.name} ({service.service_id})"
            for service in self._result.services if service.repo_ids)[:25]
        return {"found": False, "node_id": query, "candidates": candidates,
                "reason": "node not in graph"}

    def services(self) -> dict:
        return {"services": [
            {"id": service.service_id, "name": service.name,
             "repos": sorted(service.repo_ids or [])}
            for service in sorted(self._result.services,
                                  key=lambda item: item.service_id)
            if service.repo_ids],
            "commits": dict(sorted(self._commits.items()))}

    def node(self, node_id: str) -> dict:
        target, ambiguous = self._resolve_node_id(node_id)
        if ambiguous:
            return {"found": False, "node_id": node_id,
                    "reason": "ambiguous service name",
                    "candidates": ambiguous}
        described = self._describe(target)
        if described is None:
            return self._unknown(node_id)
        return {"found": True, "node": described}

    def search(self, query: str, limit: int = 20) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        limit = int(limit)
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        linked = [self._linked_node(node_id) for node_id in self._known_node_ids()]
        candidates = [record for record in linked
                      if record is not None and record.get("type") != "ContractClaim"]
        candidates.extend(self._node_lookup.search(query, limit + 1))
        by_id = {str(record["id"]): record for record in candidates}
        ranked = [(rank, record) for record in by_id.values()
                  if (rank := search_rank(record, query)) is not None]
        ranked.sort(key=lambda item: item[0])
        matches = []
        for rank, record in ranked[:limit]:
            matches.append({**record, "score": round(1.0 - rank[0] / 6, 4)})
        return {"found": bool(matches), "query": query, "matches": matches,
                "truncated": len(ranked) > limit}

    def consumers_of(self, node_id: str) -> dict:
        target, ambiguous = self._resolve_node_id(node_id)
        if ambiguous:
            return {"found": False, "node_id": node_id,
                    "reason": "ambiguous service name",
                    "candidates": ambiguous}
        consumers = []
        for edge in self._result.edges:
            if (edge.target_id == target
                    and getattr(edge, "status", "active") == "active"
                    and is_dependence(edge)):
                consumers.append({"consumer": edge.source_id,
                                  **edge_record(edge)})
        consumers.sort(key=lambda item: (item["consumer"], item["type"]))
        if not consumers and self._describe(target) is None:
            return self._unknown(node_id)
        return {"found": True, "node_id": target, "consumers": consumers}

    def trace(self, from_id: str, to_id: str, max_hops: int = 6) -> dict:
        from tracekite.services.linker.traverse import find_paths

        source, from_candidates = self._resolve_node_id(from_id)
        target, to_candidates = self._resolve_node_id(to_id)
        if from_candidates or to_candidates:
            return {"from": from_id, "to": to_id, "paths": [],
                    "found": False, "reason": "ambiguous service name",
                    "candidates": {"from": from_candidates,
                                   "to": to_candidates}}
        hops = int(max_hops)
        if not 1 <= hops <= 8:
            raise ValueError("max_hops must be between 1 and 8")
        paths = find_paths(self._result.edges, source, target, max_hops=hops)
        return {"from": from_id, "to": to_id, "resolved_from": source,
                "resolved_to": target, "from_known": self._describe(source) is not None,
                "to_known": self._describe(target) is not None,
                "paths": paths, "found": bool(paths)}

    def _neighborhood(self, node_id: str, direction: str, depth: int,
                      edge_types: list[str] | None, limit: int):
        target, ambiguous = self._resolve_node_id(node_id)
        if ambiguous:
            return None, {"found": False, "node_id": node_id,
                          "reason": "ambiguous service name",
                          "candidates": ambiguous}
        if self._describe(target) is None:
            return None, self._unknown(node_id)
        graph = bounded_neighborhood(
            self._result.edges, target, direction=direction, depth=depth,
            edge_types=edge_types, limit=limit)
        return graph, None

    def neighbors(self, node_id: str, direction: str = "both", depth: int = 1,
                  edge_types: list[str] | None = None, limit: int = 100) -> dict:
        graph, decline = self._neighborhood(
            node_id, direction, depth, edge_types, limit)
        if decline:
            return decline
        nodes = [{**(self._describe(candidate) or {"id": candidate}),
                  "distance": distance}
                 for candidate, distance in graph.distances.items()
                 if distance > 0]
        nodes.sort(key=lambda item: (item["distance"], item["id"]))
        resolved = next(iter(graph.distances))
        return {"found": True, "node_id": resolved,
                "requested_node_id": node_id, "direction": direction,
                "depth": int(depth), "neighbors": nodes,
                "edges": [edge_record(edge) for edge in graph.walk_edges],
                "total_neighbors": graph.total_neighbors,
                "truncated": graph.truncated}

    def impact(self, node_id: str, depth: int = 6, limit: int = 100,
               min_confidence: float = 0.0,
               edge_types: list[str] | None = None) -> dict:
        from tracekite.services.linker.impact_traverse import transitive_impact

        target, ambiguous = self._resolve_node_id(node_id)
        if ambiguous:
            return {"found": False, "node_id": node_id,
                    "reason": "ambiguous service name", "candidates": ambiguous}
        if self._describe(target) is None:
            return self._unknown(node_id)
        result = transitive_impact(
            self._result.edges, target, depth=depth, limit=limit,
            min_confidence=min_confidence, edge_types=edge_types)
        impacted = [{**row, "node": self._describe(row["node_id"])
                     or {"id": row["node_id"]}} for row in result.impacted]
        return {"found": True, "node_id": target,
                "requested_node_id": node_id, "impacted": impacted,
                "total_impacted": result.total_impacted,
                "truncated": result.truncated}

    def subgraph(self, node_id: str, depth: int = 2, direction: str = "both",
                 edge_types: list[str] | None = None, node_limit: int = 100,
                 edge_limit: int = 250) -> dict:
        node_limit, edge_limit = int(node_limit), int(edge_limit)
        if not 2 <= node_limit <= 500:
            raise ValueError("node_limit must be between 2 and 500")
        if not 1 <= edge_limit <= 1000:
            raise ValueError("edge_limit must be between 1 and 1000")
        graph, decline = self._neighborhood(
            node_id, direction, depth, edge_types, node_limit - 1)
        if decline:
            return decline
        nodes = [{**(self._describe(candidate) or {"id": candidate}),
                  "distance": distance}
                 for candidate, distance in graph.distances.items()]
        nodes.sort(key=lambda item: (item["distance"], item["id"]))
        edges = [edge_record(edge) for edge in graph.induced_edges]
        resolved = next(iter(graph.distances))
        return {"found": True, "node_id": resolved,
                "requested_node_id": node_id, "nodes": nodes,
                "edges": edges[:edge_limit],
                "total_nodes": graph.total_neighbors + 1,
                "returned_nodes": len(nodes),
                "total_edges": graph.total_induced_edges,
                "returned_edges": min(len(edges), edge_limit),
                "truncated": graph.truncated or len(edges) > edge_limit}

    def deprecations(self) -> dict:
        from tracekite.services.linker.deprecations import deprecation_report

        return {"contracts": deprecation_report(
            self._result.edges, self._result.rendezvous)}
