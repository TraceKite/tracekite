"""One complete, deterministic representation of an asserted graph edge."""

from tracekite.utils.evidence import as_spans


def edge_record(edge) -> dict:
    """Expose the provenance already carried by a linker edge."""
    extra = dict(getattr(edge, "extra_props", {}) or {})
    evidence = list(getattr(edge, "evidence", None) or [])
    confidence = float(getattr(edge, "confidence", 0.0) or 0.0)
    min_confidence = extra.get("min_confidence")
    max_confidence = extra.get("max_confidence")
    min_confidence = confidence if min_confidence is None else float(min_confidence)
    max_confidence = confidence if max_confidence is None else float(max_confidence)
    via = extra.get("via", []) or []
    if isinstance(via, str):
        via = [via]
    return {
        "source": edge.source_id,
        "target": edge.target_id,
        "source_label": str(getattr(edge, "source_label", "") or ""),
        "target_label": str(getattr(edge, "target_label", "") or ""),
        "type": edge.type,
        "confidence": round(confidence, 4),
        "min_confidence": round(min_confidence, 4),
        "max_confidence": round(max_confidence, 4),
        "detected_by": str(getattr(edge, "detected_by", "") or ""),
        "match_type": str(getattr(edge, "match_type", "") or ""),
        "via": sorted(str(value) for value in via),
        "claim_key": str(getattr(edge, "claim_key", "") or ""),
        "source_repo": str(getattr(edge, "source_repo_id", "") or ""),
        "target_repo": str(getattr(edge, "target_repo_id", "") or ""),
        "cross_repo": bool(getattr(edge, "cross_repo", False)),
        "evidence": evidence,
        "spans": as_spans(evidence),
    }
