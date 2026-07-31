"""Which edges are served, and at what confidence.

Three decisions that only make sense together, so they are one module rather
than three helpers scattered through the engine: corroborating resolvers fuse
into one edge, the confidence floor decides whether that edge is served or
merely visible, and an operator's review decision overrides both.

Order is the point. Running the floor before fusion would mark an edge
`candidate` that two resolvers independently agreed on — precisely the edge
fusion exists to promote.
"""

import logging

from adduce.services.linker.base import fuse_edges, load_promotions
# Annotates finalize_edges' `combined` parameter. Python 3.12 evaluates
# function annotations eagerly, so an unimported name here is an
# import-time NameError on the deployment runtime — invisible on a 3.14
# dev box, where PEP 649 defers evaluation.
from adduce.services.linker.values import ResolverOutput
from adduce.telemetry import timed

logger = logging.getLogger(__name__)

# Matches `floor` in confidence.yml; used when the file omits it. Edges below
# it are marked `candidate`, not `active`, and excluded from default answers.
_DEFAULT_FLOOR = 0.6
_DEFAULT_FUSION_CAP = 0.99


def apply_confidence_floor(ctx, edges: list) -> None:
    """Mark sub-floor edges `candidate` instead of `active` (design §5.5).

    Precision first, recall as flagged candidates: a low-confidence match stays
    visible and inspectable but is excluded from default answers, rather than
    being deleted (invisible) or served as fact (a silent lie). Read paths
    filter on `status = 'active'`.
    """
    floor = float(ctx.confidence.get("floor", _DEFAULT_FLOOR))
    for edge in edges:
        if edge.confidence < floor and edge.status == "active":
            edge.status = "candidate"
            ctx.count("edges_below_floor")


def _apply_promotions(ctx, edges: list, promotions) -> None:
    """Replay operator review decisions: promotions survive every
    relink, rejections stay rejected even though resolvers recreate them."""
    decisions = {(p["source"], p.get("type", ""), p["target"]):
                 p.get("decision", "promote") for p in promotions}
    if not decisions:
        return
    for edge in edges:
        decision = decisions.get((edge.source_id, edge.type, edge.target_id))
        if decision == "promote" and edge.status == "candidate":
            edge.status = "active"
            edge.extra_props["promoted"] = True
            ctx.count("edges_promoted")
        elif decision == "reject":
            edge.status = "rejected"
            ctx.count("edges_rejected")


def finalize_edges(ctx, combined: ResolverOutput, promotions) -> list:
    """Fuse corroborating edges, then decide which are served.

    One step, not three: fusion changes a confidence, the floor reads it, and
    a promotion overrides both. Splitting them would invite a caller to run
    the floor against unfused confidences and mark an edge `candidate` that
    two resolvers agreed on.
    """
    with timed(ctx.timings, "phase.fuse"):
        cap = float(ctx.confidence.get("fusion_cap", _DEFAULT_FUSION_CAP))
        edges = fuse_edges(combined.edges, cap)
        apply_confidence_floor(ctx, edges)
        if promotions is None:
            try:
                promotions = load_promotions()
            except Exception:                                 # noqa: BLE001
                # Reviews refine, never block: a corrupt decisions
                # file must not fail the graph. Counted, because a link
                # that silently ignored an operator's decisions would be
                # worse than one that failed.
                ctx.count("promotions_unreadable")
                promotions = []
        _apply_promotions(ctx, edges, promotions)
    return edges
