"""The one gate every claim passes through on its way into the graph.

Moved out of `ingest_claims.py` verbatim so emitter modules can import it
without a cycle. The centrality is the point and must survive any future
move: provenance stamping and template rejection happen HERE so a new
emitter cannot forget them.
"""

from adduce.models.graph_models import GraphEdge
from adduce.services.claims import (
    ContractClaim, claim_to_node, is_unrendered_template,
)
from adduce.services.file_classifier import classify
from adduce.services.ingest_source import IngestSink
from adduce.utils.evidence import evidence_path


def add_claim(repo_id: str, claim: ContractClaim, evidence_node_id: str,
              sink: IngestSink) -> None:
    """Persist one claim, stamping provenance from its evidence path.

    Stamped here rather than at each call site so a new emitter cannot forget
    to do it: every claim's file of origin is already in its evidence, and
    test/vendored files must never contribute joinable facts.
    """
    # A name that is still a template was never substituted, so it identifies
    # nothing. Rejected here rather than at each of the ten svcname emitters,
    # for the same reason provenance is stamped here: a new emitter cannot
    # forget. Counted so the drop is visible, per decline-don't-guess.
    if claim.kind in ("svcname", "image") and is_unrendered_template(
            claim.service_hint or claim.key.rpartition(":")[2]):
        sink.count_claim(f"{claim.kind}_unrendered_template")
        return
    if not claim.provenance and claim.evidence:
        claim.provenance = classify(evidence_path(claim.evidence[0])).reason
    node = claim_to_node(claim)
    if not sink.add_node(node):
        return
    sink.count_claim(claim.kind)
    if claim.provenance:
        sink.count_claim(f"_{claim.provenance}")
    sink.add_edge(GraphEdge(
        source_id=node.id, target_id=evidence_node_id, repo_id=repo_id,
        type="EVIDENCED_BY", evidence=claim.evidence[:1],
        detected_by="ingestion.claims",
    ))
