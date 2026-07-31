"""The estate as group boxes: navigable at 1,000 repos.

Its own route module for the same reason `trace.py` is: `links.py`
predates the 300-line rule and must not grow. Orchestration only — the
folding rules live in `services/linker/rollup_view.py`, so a library host
aggregating its own map gets the identical answer.
"""

from fastapi import APIRouter, Query

from adduce.db.neo4j_client import get_session

router = APIRouter()


@router.get("/api/v2/service-map/aggregate")
async def service_map_aggregate(
        by: str = Query("domain", pattern="^(domain|team)$"),
        min_confidence: float = Query(0.6, ge=0.0, le=1.0)):
    """The estate as group boxes: navigable at 1,000 repos.

    Orchestration only — the folding rules (min-confidence rollup,
    intra-group counts, the explicit unowned group) live in core, so a
    library host aggregating its own map gets the identical answer.
    """
    from adduce.services.linker.rollup_view import (
            aggregate_service_map, ownership_from_rows)

    with get_session() as session:
        services = session.run(
            "MATCH (s:Service) RETURN s.id AS id, s.name AS name",
        ).data()
        edges = session.run(
            "MATCH (a:Service)-[r:CALLS_SERVICE|ROUTES_TO]->(b:Service) "
            "WHERE r.created_by = 'linker' "
            "AND coalesce(r.status, 'active') = 'active' "
            "AND coalesce(r.min_confidence, r.confidence, 0) >= $minc "
            "RETURN a.id AS source, b.id AS target, type(r) AS type, "
            "coalesce(r.min_confidence, r.confidence, 0) AS confidence",
            minc=min_confidence).data()
        ownership = None
        if by == "team":
            rows = session.run(
                "MATCH (s:Service)-[r:OWNED_BY]->(t:Team) "
                "WHERE coalesce(r.status, 'active') = 'active' "
                "RETURN s.id AS service, t.name AS team "
                "ORDER BY s.id, t.name",
            ).data()
            ownership = ownership_from_rows(rows)
    return aggregate_service_map(services, edges, by=by,
                                 ownership=ownership)
