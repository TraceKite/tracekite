"""Find nodes in one repository by name, label or path, best match first."""

from tracekite.db.neo4j_client import get_session
from tracekite.models.api_models import SearchResult

# Exact name, then prefix, then anywhere in the name, then the path only. With
# no order the LIMIT kept whatever the store yielded first: in excalidraw,
# "Scene" returned 100 folders, methods and interfaces, but not `class Scene`.
_SEARCH = (
    "MATCH (n:GraphNode) WHERE n.repo_id = $repo_id "
    "WITH n, toLower($q) AS q, toLower(coalesce(n.name, '')) AS name, "
    "toLower(coalesce(n.label, '')) AS label "
    "WHERE name CONTAINS q OR label CONTAINS q "
    "OR toLower(coalesce(n.path, '')) CONTAINS q "
    "WITH n, CASE WHEN name = q OR label = q THEN 0 "
    "WHEN name STARTS WITH q OR label STARTS WITH q THEN 1 "
    "WHEN name CONTAINS q OR label CONTAINS q THEN 2 ELSE 3 END AS tier "
    "RETURN n.id AS id, n.type AS type, n.name AS name, n.label AS label, "
    "n.path AS path, tier ORDER BY tier, size(coalesce(n.name, '')), n.id "
    "LIMIT $limit")


def search_nodes(repo_id: str, query: str, limit: int = 20) -> list[SearchResult]:
    with get_session() as session:
        result = session.run(_SEARCH, repo_id=repo_id, q=query, limit=limit)
        return [SearchResult(id=r["id"], type=r["type"],
                             label=r["label"] or r["name"], path=r["path"],
                             score=1.0 - r["tier"] / 4) for r in result]
