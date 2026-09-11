"""Stored graph reads for the estate map and cross-repository bridges."""

from evigraph.db.neo4j_client import get_session
from evigraph.services.linker.crossings import assemble_crossings
from evigraph.services.linker.map_view import assemble_service_map

MAP_EDGE_TYPES = (
    "CALLS_SERVICE", "ROUTES_TO", "BUILT_FROM", "PUBLISHES_TO",
    "CONSUMES_FROM", "FANS_OUT_TO",
)


def read_service_map(min_confidence: float, limit: int) -> dict:
    edge_filter = "|".join(MAP_EDGE_TYPES)
    with get_session() as session:
        node_rows = session.run(
            "MATCH (s:Service) RETURN s.id AS id, s.name AS name, "
            "s.repo_ids AS repo_ids, 'Gateway' IN labels(s) AS is_gateway",
        ).data()
        edge_rows = session.run(
            f"MATCH (a)-[r:{edge_filter}]->(b) "
            "WHERE r.created_by = 'linker' "
            "AND coalesce(r.status, 'active') = 'active' "
            "AND coalesce(r.min_confidence, r.confidence, 0) >= $minc "
            "RETURN a.id AS source, labels(a) AS source_labels, "
            "coalesce(a.name, a.id) AS source_name, a.scope AS source_scope, "
            "b.id AS target, labels(b) AS target_labels, "
            "coalesce(b.name, b.id) AS target_name, b.scope AS target_scope, "
            "type(r) AS type, r.confidence AS confidence, "
            "r.min_confidence AS min_confidence, "
            "r.max_confidence AS max_confidence, r.via AS via, "
            "r.weight AS weight, r.path_prefix AS path_prefix, "
            "r.source_repo_id AS source_repo_id, r.evidence AS evidence "
            "ORDER BY r.confidence DESC LIMIT $limit",
            minc=min_confidence, limit=limit,
        ).data()
        total_edges = session.run(
            f"MATCH ()-[r:{edge_filter}]->() WHERE r.created_by = 'linker' "
            "AND coalesce(r.status, 'active') = 'active' "
            "AND coalesce(r.min_confidence, r.confidence, 0) >= $minc "
            "RETURN count(r) AS c",
            minc=min_confidence,
        ).single()["c"]
    return assemble_service_map(node_rows, edge_rows, total_edges)


def read_code_bridges(repo_ids: list[str], limit: int) -> dict:
    """Return both cited halves of cross-repository contract joins."""
    with get_session() as session:
        rows = session.run(
            "MATCH (a:GraphNode)-[i:INVOKES]->(c)<-[e:EXPOSES]-(b:GraphNode) "
            "WHERE a.repo_id IN $repos AND b.repo_id IN $repos "
            "RETURN a.id AS a_id, a.name AS a_name, a.type AS a_type, "
            "a.path AS a_path, a.repo_id AS a_repo, "
            "b.id AS b_id, b.name AS b_name, b.type AS b_type, "
            "b.path AS b_path, b.repo_id AS b_repo, "
            "c.id AS c_id, labels(c)[0] AS c_label, "
            "coalesce(c.method + ' ' + c.path_template, c.rpc, c.name, c.id) "
            "AS c_name, i.confidence AS in_conf, i.evidence AS in_ev, "
            "e.confidence AS ex_conf, e.evidence AS ex_ev "
            "LIMIT $limit",
            repos=repo_ids, limit=limit,
        ).data()
    return {**assemble_crossings(rows), "repos": repo_ids}
