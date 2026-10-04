"""The node and edge selection behind one per-repository view.

A view is a ranked slice of node types plus the context that makes it
readable: the direct parents and containment ancestors of what was picked, and
the source side of the view's own edges so none of them dangles. Context
follows only edges the view draws — anything else arrives as an orphan.
"""

from typing import Optional

from tracekite.db.neo4j_client import get_session
from tracekite.models.api_models import GraphLink, GraphNode
from tracekite.services.graph_records import (
    EDGE_RETURN, link_from_record, node_from_props,
)


def collect_nodes(result, nodes: list, node_ids: set) -> None:
    for record in result:
        node = node_from_props(record["props"])
        if node.id and node.id not in node_ids:
            nodes.append(node)
            node_ids.add(node.id)


def get_view_graph(repo_id: str, node_types: list[str], edge_types: list[str],
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

        collect_nodes(session.run(
            f"MATCH (n:GraphNode) WHERE n.repo_id = $repo_id {type_filter} "
            f"RETURN properties(n) AS props {order_clause} LIMIT $limit",
            repo_id=repo_id, node_types=node_types, limit=limit,
        ), nodes, node_ids)

        if node_ids:
            # Direct parents of returned nodes (e.g. Files for Classes), over
            # edges this view draws: any edge pulled in evidence claims, which
            # then rendered as orphans and spent the budget meant for handlers.
            collect_nodes(session.run(
                "MATCH (parent:GraphNode)-[r]->(child:GraphNode) "
                "WHERE parent.repo_id = $repo_id AND child.repo_id = $repo_id "
                "AND child.id IN $node_ids AND NOT parent.id IN $node_ids "
                "AND ($edge_types = [] OR type(r) IN $edge_types) "
                "RETURN DISTINCT properties(parent) AS props LIMIT $lim",
                repo_id=repo_id, node_ids=list(node_ids), edge_types=edge_types,
                lim=max(1, limit // 2),
            ), nodes, node_ids)

            # Folder/Repo ancestors so containment paths are complete.
            collect_nodes(session.run(
                "MATCH (ancestor:GraphNode)-[:CONTAINS]->(descendant:GraphNode) "
                "WHERE ancestor.repo_id = $repo_id AND descendant.repo_id = $repo_id "
                "AND descendant.id IN $node_ids AND NOT ancestor.id IN $node_ids "
                "RETURN DISTINCT properties(ancestor) AS props LIMIT $lim",
                repo_id=repo_id, node_ids=list(node_ids),
                lim=max(1, limit // 4),
            ), nodes, node_ids)

        if node_ids and edge_types:
            # Source-side neighbors so edges like EXPOSES_API are not dangling.
            collect_nodes(session.run(
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
        links = [link_from_record(record) for record in edge_result]

    return nodes, links
