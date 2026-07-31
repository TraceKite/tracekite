"""Does the cited line still say that?

Evidence rots: an artifact scanned last month cites lines the tree has
since rewritten, and silent rot is worse than none — the receipt is the
product. This pass re-reads every citation out of the CURRENT tree and
classifies it, then downgrades the confidence of edges built on rot.
Never deletes: a downgraded edge below the floor becomes `candidate` —
visible, inspectable, flagged — because deleting it would erase exactly
the thing an operator needs to see aged out.

Verdicts are deliberately asymmetric. `stale` requires POSITIVE proof
(file gone, cited line past EOF, or the claim's own token absent around
the cited line); anything this pass cannot check mechanically is
`unverifiable` and counted, never downgraded — wrongly aging a good edge
is the same sin as inventing one.
"""

from adduce.utils.evidence import parse_evidence

# How far a cited line may have drifted and still count as saying it.
_RADIUS = 3
_STALE_FACTOR_DEFAULT = 0.7


def claim_token(kind: str, key: str) -> str | None:
    """The fragment of a claim's key its cited line should still contain.

    Returns None when no fragment is distinctive enough to test — those
    claims are unverifiable by this pass, not stale.
    """
    if kind == "http":
        template = key.rpartition(":")[2]
        return template if len(template) > 3 else None
    if kind in ("svcname", "topic", "cfgdef", "cfgread", "dataset", "db"):
        token = key.rpartition(":")[2]
        return token if len(token) > 2 else None
    if kind in ("grpcop", "grpcstub"):
        rpc = key.rpartition("/")[2]
        return rpc if len(rpc) > 2 else None
    return None


def _verdict(span, token: str, text: str | None) -> str:
    if text is None:
        return "stale_file"
    lines = text.split("\n")
    if span.line_start > len(lines):
        return "stale_line"
    lo = max(0, span.line_start - 1 - _RADIUS)
    hi = min(len(lines), (span.line_end or span.line_start) + _RADIUS)
    window = "\n".join(lines[lo:hi])
    return "ok" if token in window else "stale_line"


def reverify(claims: list, read_file) -> dict:
    """Every citation classified against the current tree.

    ``read_file(path) -> str | None`` is injected so the decision logic
    stays pure; None means the file no longer exists. Returns stale
    citations with their reasons plus counts — the shape
    ``downgrade_stale`` consumes.
    """
    stale: dict[str, str] = {}
    counts = {"ok": 0, "stale": 0, "unverifiable": 0}
    seen: set[str] = set()
    for claim in claims:
        token = claim_token(claim.kind, claim.key)
        for evidence in claim.evidence or []:
            if evidence in seen:
                continue
            seen.add(evidence)
            span = parse_evidence(evidence)
            if token is None or span.line_start is None:
                counts["unverifiable"] += 1
                continue
            verdict = _verdict(span, token, read_file(span.file))
            if verdict == "ok":
                counts["ok"] += 1
            else:
                counts["stale"] += 1
                stale[evidence] = verdict
    return {"stale": stale, "counts": counts}


def downgrade_stale(edges: list, stale: dict, confidence: dict) -> dict:
    """Scale down edges citing rotten evidence; below the floor they become
    `candidate`. Nothing is removed and nothing is rejected — rot ages an
    assertion, it does not refute it."""
    factor = float(confidence.get("stale_evidence_factor",
                                  _STALE_FACTOR_DEFAULT))
    floor = float(confidence.get("floor", 0.6))
    downgraded = []
    for edge in edges:
        rotten = sorted(e for e in (edge.evidence or []) if e in stale)
        if not rotten:
            continue
        edge.confidence = round(edge.confidence * factor, 4)
        edge.extra_props["stale_evidence"] = rotten
        if edge.confidence < floor and edge.status == "active":
            edge.status = "candidate"
        downgraded.append({"source": edge.source_id, "type": edge.type,
                           "target": edge.target_id,
                           "confidence": edge.confidence,
                           "status": edge.status, "stale": rotten})
    return {"downgraded": downgraded, "factor": factor}
