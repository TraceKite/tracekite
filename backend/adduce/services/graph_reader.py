"""Neo4j graph reader — typed relationships only (Invariant 1).

The store contains no RELATES_TO edges: traversals either name concrete
relationship types or match untyped [r] and report type(r). Lite-tier edges
omit provenance properties; LITE_DEFAULTS are applied here on read.
"""

import json
import logging
from typing import Optional

from adduce.db.neo4j_client import get_session
from adduce.models.api_models import (
    GraphLink, GraphNode, GraphResponse, GraphStats, NodeDetail,
    RepoSummary, SearchResult,
)
from adduce.models.graph_models import LITE_DEFAULTS

logger = logging.getLogger(__name__)

VIEW_MODES = {
    "overview": {
        "node_types": ["Repo", "Folder", "File", "Class", "Dependency", "ApiEndpoint"],
        "edge_types": ["CONTAINS", "DECLARES", "DEPENDS_ON", "EXPOSES_API"],
        "limit": 300,
        "priority": {"Repo": 1, "Dependency": 2, "ApiEndpoint": 2,
                     "Class": 3, "File": 4, "Folder": 5},
    },
    "architecture": {
        "node_types": ["Repo", "Folder", "File", "Class", "Interface", "ApiEndpoint",
                       "Dependency", "Config", "DockerResource", "KubernetesResource"],
        "edge_types": ["CONTAINS", "DECLARES", "EXPOSES_API", "DEPENDS_ON"],
        "limit": 400,
        "priority": {"Repo": 1, "ApiEndpoint": 2, "DockerResource": 2,
                     "KubernetesResource": 2, "Dependency": 3, "Class": 3,
                     "Interface": 4, "Config": 4, "File": 5, "Folder": 6},
    },
    "code": {
        "node_types": ["Folder", "File", "Class", "Interface", "Method", "Function"],
        "edge_types": ["CONTAINS", "DECLARES", "CALLS"],
        "limit": 500,
        "priority": {"Class": 1, "Interface": 1, "Method": 2, "Function": 2,
                     "File": 4, "Folder": 5},
    },
    "api": {
        "node_types": ["Class", "Method", "Function", "ApiEndpoint", "File"],
        "edge_types": ["CONTAINS", "DECLARES", "EXPOSES_API", "CALLS"],
        "limit": 300,
        "priority": {"ApiEndpoint": 1, "Method": 2, "Function": 2,
                     "Class": 3, "File": 4},
    },
    "dependencies": {
        "node_types": ["Repo", "File", "Dependency"],
        "edge_types": ["CONTAINS", "DEPENDS_ON"],
        "limit": 400,
        "priority": {"Dependency": 1, "File": 3, "Repo": 4},
    },
    "impact": {"node_types": [], "edge_types": [], "limit": 200, "priority": {}},
}

NODE_SIZES = {
    "Repo": 20, "Folder": 12, "File": 8, "Class": 10, "Interface": 9,
    "Method": 6, "Function": 6, "ApiEndpoint": 11, "Dependency": 7,
    "Config": 6, "DockerResource": 9, "KubernetesResource": 9,
}

CORE_NODE_PROPS = {"id", "type", "name", "label", "path", "language", "repo_id",
                   "metadata", "created_at", "updated_at"}

EDGE_RETURN = (
    "a.id AS source, b.id AS target, type(r) AS type, r.label AS label, "
    "r.weight AS weight, r.confidence AS confidence, r.origin AS origin, "
    "r.detected_by AS detected_by"
)


def _parse_json(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _to_native_dt(value):
    return value.to_native() if hasattr(value, "to_native") else value


def _json_safe(value):
    """Neo4j temporal values are not JSON-serializable; fold them as ISO strings."""
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    to_native = getattr(value, "to_native", None)
    if callable(to_native):
        native = to_native()
        return native.isoformat() if hasattr(native, "isoformat") else str(native)
    return value


def _node_from_props(props: dict, size_bonus: int = 0) -> GraphNode:
    metadata = _parse_json(props.get("metadata"))
    for key, value in props.items():
        if key not in CORE_NODE_PROPS and value is not None:
            metadata.setdefault(key, _json_safe(value))
    node_type = props.get("type") or ""
    name = props.get("name") or ""
    return GraphNode(
        id=props.get("id") or "",
        type=node_type,
        label=props.get("label") or name,
        name=name,
        path=props.get("path"),
        language=props.get("language") or "",
        size=NODE_SIZES.get(node_type, 7) + size_bonus,
        group=node_type,
        metadata=metadata,
    )


def _link_from_record(record) -> GraphLink:
    confidence = record["confidence"]
    return GraphLink(
        source=record["source"],
        target=record["target"],
        type=record["type"],
        label=record["label"] or record["type"].lower(),
        value=int(record["weight"] or 1),
        confidence=float(confidence) if confidence is not None
        else LITE_DEFAULTS["confidence"],
        origin=record["origin"] or LITE_DEFAULTS["origin"],
        detected_by=record["detected_by"],
    )


def _repo_summary(props: dict) -> RepoSummary:
    coverage = _parse_json(props.get("parse_coverage_totals"))
    return RepoSummary(
        id=props.get("id") or "",
        name=props.get("name") or "",
        owner=props.get("owner") or "",
        repo=props.get("repo") or "",
        github_url=props.get("github_url") or "",
        branch=props.get("branch") or "main",
        last_ingested_at=_to_native_dt(props.get("last_ingested_at")),
        ingestion_status=props.get("ingestion_status") or "unknown",
        lifecycle_state=props.get("lifecycle_state"),
        head_commit_sha=props.get("head_commit_sha"),
        node_count=props.get("node_count") or 0,
        edge_count=props.get("edge_count") or 0,
        parse_coverage=coverage or None,
        claims_by_kind=_parse_json(props.get("claims_by_kind")) or None,
        linked_at=_to_native_dt(props.get("linked_at")),
    )


def get_repo(repo_id: str) -> Optional[RepoSummary]:
    with get_session() as session:
        record = session.run(
            "MATCH (r:Repo {id: $repo_id}) RETURN properties(r) AS props",
            repo_id=repo_id,
        ).single()
        return _repo_summary(record["props"]) if record else None


def list_repos() -> list[RepoSummary]:
    with get_session() as session:
        result = session.run(
            "MATCH (r:Repo) RETURN properties(r) AS props "
            "ORDER BY r.last_ingested_at DESC"
        )
        return [_repo_summary(record["props"]) for record in result]


def get_graph(repo_id: str, view: str = "overview",
              node_types: Optional[list[str]] = None,
              edge_types: Optional[list[str]] = None,
              search: Optional[str] = None,
              limit: int = 300,
              focus_node_id: Optional[str] = None,
              depth: int = 2) -> GraphResponse:
    """Retrieve graph data for visualization."""
    view_config = VIEW_MODES.get(view, VIEW_MODES["overview"])
    selected_node_types = node_types or view_config["node_types"]
    selected_edge_types = edge_types or view_config["edge_types"]
    effective_limit = min(limit or view_config["limit"], 500)

    repo = get_repo(repo_id)

    if view == "impact" and focus_node_id:
        nodes, links = _get_impact_graph(repo_id, focus_node_id, depth,
                                         effective_limit)
    elif search:
        nodes, links = _get_search_graph(repo_id, search, effective_limit)
    else:
        nodes, links = _get_view_graph(repo_id, selected_node_types,
                                       selected_edge_types, effective_limit,
                                       view_config.get("priority"))

    return GraphResponse(repo=repo, stats=_compute_stats(nodes, links),
                         nodes=nodes, links=links)


def _collect_nodes(result, nodes: list, node_ids: set) -> None:
    for record in result:
        node = _node_from_props(record["props"])
        if node.id and node.id not in node_ids:
            nodes.append(node)
            node_ids.add(node.id)


def _get_view_graph(repo_id: str, node_types: list[str], edge_types: list[str],
                    limit: int, priority: Optional[dict[str, int]] = None
                    ) -> tuple[list[GraphNode], list[GraphLink]]:
    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
    node_ids: set[str] = set()

    with get_session() as session:
        type_filter = "AND n.type IN $node_types" if node_types else ""
        if priority:
            cases = " ".join(f"WHEN '{t}' THEN {p}" for t, p in priority.items())
            order_clause = f"ORDER BY CASE n.type {cases} ELSE 99 END, n.name"
        else:
            order_clause = "ORDER BY n.name"

        _collect_nodes(session.run(
            f"MATCH (n:GraphNode) WHERE n.repo_id = $repo_id {type_filter} "
            f"RETURN properties(n) AS props {order_clause} LIMIT $limit",
            repo_id=repo_id, node_types=node_types, limit=limit,
        ), nodes, node_ids)

        if node_ids:
            # Direct parents of returned nodes (e.g. Files for Classes).
            _collect_nodes(session.run(
                "MATCH (parent:GraphNode)-[r]->(child:GraphNode) "
                "WHERE parent.repo_id = $repo_id AND child.repo_id = $repo_id "
                "AND child.id IN $node_ids AND NOT parent.id IN $node_ids "
                "RETURN DISTINCT properties(parent) AS props LIMIT $lim",
                repo_id=repo_id, node_ids=list(node_ids),
                lim=max(1, limit // 2),
            ), nodes, node_ids)

            # Folder/Repo ancestors so containment paths are complete.
            _collect_nodes(session.run(
                "MATCH (ancestor:GraphNode)-[:CONTAINS]->(descendant:GraphNode) "
                "WHERE ancestor.repo_id = $repo_id AND descendant.repo_id = $repo_id "
                "AND descendant.id IN $node_ids AND NOT ancestor.id IN $node_ids "
                "RETURN DISTINCT properties(ancestor) AS props LIMIT $lim",
                repo_id=repo_id, node_ids=list(node_ids),
                lim=max(1, limit // 4),
            ), nodes, node_ids)

        if node_ids and edge_types:
            # Source-side neighbors so edges like EXPOSES_API are not dangling.
            _collect_nodes(session.run(
                "MATCH (neighbor:GraphNode)-[r]->(n:GraphNode) "
                "WHERE neighbor.repo_id = $repo_id AND n.repo_id = $repo_id "
                "AND n.id IN $node_ids AND NOT neighbor.id IN $node_ids "
                "AND type(r) IN $edge_types "
                "RETURN DISTINCT properties(neighbor) AS props LIMIT $lim",
                repo_id=repo_id, node_ids=list(node_ids),
                edge_types=edge_types, lim=max(1, limit // 4),
            ), nodes, node_ids)

        edge_filter = "AND type(r) IN $edge_types" if edge_types else ""
        edge_result = session.run(
            f"MATCH (a:GraphNode)-[r]->(b:GraphNode) "
            f"WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
            f"AND a.id IN $node_ids AND b.id IN $node_ids {edge_filter} "
            f"RETURN {EDGE_RETURN}",
            repo_id=repo_id, node_ids=list(node_ids), edge_types=edge_types,
        )
        links = [_link_from_record(record) for record in edge_result]

    return nodes, links


def _get_impact_graph(repo_id: str, focus_node_id: str, depth: int,
                      limit: int) -> tuple[list[GraphNode], list[GraphLink]]:
    """Impact view: the focus node plus neighbors within depth hops."""
    nodes: list[GraphNode] = []
    node_ids: set[str] = set()

    with get_session() as session:
        focus_record = session.run(
            "MATCH (n:GraphNode {id: $focus_id, repo_id: $repo_id}) "
            "RETURN properties(n) AS props",
            focus_id=focus_node_id, repo_id=repo_id,
        ).single()
        if focus_record:
            node = _node_from_props(focus_record["props"], size_bonus=5)
            nodes.append(node)
            node_ids.add(node.id)

        # Variable-length bounds cannot be parameters; depth is validated 1..5.
        _collect_nodes(session.run(
            f"MATCH (focus:GraphNode {{id: $focus_id, repo_id: $repo_id}})"
            f"-[*1..{int(depth)}]-(neighbor:GraphNode) "
            f"WHERE neighbor.repo_id = $repo_id "
            f"RETURN DISTINCT properties(neighbor) AS props LIMIT $limit",
            focus_id=focus_node_id, repo_id=repo_id, limit=limit,
        ), nodes, node_ids)

        edge_result = session.run(
            f"MATCH (a:GraphNode)-[r]->(b:GraphNode) "
            f"WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
            f"AND a.id IN $node_ids AND b.id IN $node_ids "
            f"RETURN {EDGE_RETURN}",
            repo_id=repo_id, node_ids=list(node_ids),
        )
        links = [_link_from_record(record) for record in edge_result]

    return nodes, links


def _get_search_graph(repo_id: str, search: str,
                      limit: int) -> tuple[list[GraphNode], list[GraphLink]]:
    nodes: list[GraphNode] = []
    node_ids: set[str] = set()

    with get_session() as session:
        _collect_nodes(session.run(
            "MATCH (n:GraphNode) WHERE n.repo_id = $repo_id "
            "AND (toLower(n.name) CONTAINS toLower($search) "
            "OR toLower(n.label) CONTAINS toLower($search) "
            "OR toLower(n.path) CONTAINS toLower($search)) "
            "RETURN properties(n) AS props LIMIT $limit",
            repo_id=repo_id, search=search, limit=limit,
        ), nodes, node_ids)

        links: list[GraphLink] = []
        if node_ids:
            edge_result = session.run(
                f"MATCH (a:GraphNode)-[r]->(b:GraphNode) "
                f"WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id "
                f"AND a.id IN $node_ids AND b.id IN $node_ids "
                f"RETURN {EDGE_RETURN}",
                repo_id=repo_id, node_ids=list(node_ids),
            )
            links = [_link_from_record(record) for record in edge_result]

    return nodes, links


def search_nodes(repo_id: str, query: str, limit: int = 20) -> list[SearchResult]:
    with get_session() as session:
        result = session.run(
            "MATCH (n:GraphNode) WHERE n.repo_id = $repo_id "
            "AND (toLower(n.name) CONTAINS toLower($q) "
            "OR toLower(n.label) CONTAINS toLower($q) "
            "OR toLower(n.path) CONTAINS toLower($q)) "
            "RETURN n.id AS id, n.type AS type, n.name AS name, "
            "n.label AS label, n.path AS path LIMIT $limit",
            repo_id=repo_id, q=query, limit=limit,
        )
        return [SearchResult(id=r["id"], type=r["type"],
                             label=r["label"] or r["name"], path=r["path"],
                             score=1.0) for r in result]


def get_node_details(repo_id: str, node_id: str) -> Optional[NodeDetail]:
    with get_session() as session:
        record = session.run(
            "MATCH (n:GraphNode {id: $node_id, repo_id: $repo_id}) "
            "RETURN properties(n) AS props",
            node_id=node_id, repo_id=repo_id,
        ).single()
        if not record:
            return None
        node = _node_from_props(record["props"])

        def _rel_rows(query: str) -> list[dict]:
            rows = []
            for r in session.run(query, node_id=node_id, repo_id=repo_id):
                confidence = r["confidence"]
                rows.append({
                    "node_id": r["nid"],
                    "node_type": r["ntype"],
                    "node_label": r["nlabel"],
                    "relationship": r["rel_type"],
                    "relationship_label": r["rel_label"] or r["rel_type"].lower(),
                    "confidence": float(confidence) if confidence is not None
                    else LITE_DEFAULTS["confidence"],
                    "origin": r["origin"] or LITE_DEFAULTS["origin"],
                    "detected_by": r["detected_by"],
                    "evidence": list(r["evidence"] or []),
                })
            return rows

        incoming = _rel_rows(
            "MATCH (a:GraphNode)-[r]->(n:GraphNode {id: $node_id, repo_id: $repo_id}) "
            "WHERE a.repo_id = $repo_id "
            "RETURN a.id AS nid, a.type AS ntype, a.label AS nlabel, "
            "type(r) AS rel_type, r.label AS rel_label, r.confidence AS confidence, "
            "r.origin AS origin, r.detected_by AS detected_by, r.evidence AS evidence "
            "LIMIT 50"
        )
        outgoing = _rel_rows(
            "MATCH (n:GraphNode {id: $node_id, repo_id: $repo_id})-[r]->(b:GraphNode) "
            "WHERE b.repo_id = $repo_id "
            "RETURN b.id AS nid, b.type AS ntype, b.label AS nlabel, "
            "type(r) AS rel_type, r.label AS rel_label, r.confidence AS confidence, "
            "r.origin AS origin, r.detected_by AS detected_by, r.evidence AS evidence "
            "LIMIT 50"
        )

        neighbors_result = session.run(
            "MATCH (n:GraphNode {id: $node_id, repo_id: $repo_id})--(m:GraphNode) "
            "RETURN DISTINCT m.id AS id, m.type AS type, m.label AS label, "
            "m.path AS path LIMIT 50",
            node_id=node_id, repo_id=repo_id,
        )
        neighbors = [{"id": r["id"], "type": r["type"], "label": r["label"],
                      "path": r["path"]} for r in neighbors_result]

        return NodeDetail(node=node, incoming=incoming, outgoing=outgoing,
                          neighbors=neighbors, code_snippet=None)


def get_neighbors(repo_id: str, node_id: str, depth: int = 1) -> dict:
    with get_session() as session:
        result = session.run(
            f"MATCH path = (n:GraphNode {{id: $node_id, repo_id: $repo_id}})"
            f"-[*1..{int(depth)}]-(neighbor:GraphNode) "
            f"WHERE neighbor.repo_id = $repo_id AND neighbor.id <> $node_id "
            f"RETURN DISTINCT neighbor.id AS id, neighbor.type AS type, "
            f"neighbor.label AS label, neighbor.path AS path, "
            f"length(path) AS distance LIMIT 100",
            node_id=node_id, repo_id=repo_id,
        )
        neighbors = [{"id": r["id"], "type": r["type"], "label": r["label"],
                      "path": r["path"], "distance": r["distance"]} for r in result]
        return {"neighbors": neighbors, "count": len(neighbors)}


def _compute_stats(nodes: list[GraphNode], links: list[GraphLink]) -> GraphStats:
    stats = GraphStats(total_nodes=len(nodes), total_edges=len(links))
    for node in nodes:
        stats.node_types[node.type] = stats.node_types.get(node.type, 0) + 1
        if node.type == "File":
            stats.files += 1
        elif node.type == "ApiEndpoint":
            stats.apis += 1
        elif node.type == "Dependency":
            stats.dependencies += 1
    for link in links:
        stats.edge_types[link.type] = stats.edge_types.get(link.type, 0) + 1
    return stats
