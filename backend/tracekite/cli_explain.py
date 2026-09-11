"""`tracekite explain`: why one edge exists, measured row included.

Split from `cli.py` at its size limit — the derivation of one edge is a
self-contained answer (rendezvous key, resolver, transforms, evidence,
and the measured interval behind the confidence), and the main module
keeps only the pipeline commands.
"""

import sys

from tracekite.cli_emit import emit


def cmd_explain(args) -> int:
    """Why one edge exists — the evidence on both sides, and what matched."""
    from tracekite.db.memory_store import InMemoryLinkerStore
    from tracekite.services.linker.engine import link
    from tracekite.wire import ExplainReport

    from tracekite.cli import _scan_all

    scanned = _scan_all(args.paths, args.hmac_key)
    store = InMemoryLinkerStore([sink for _rid, sink in scanned])
    result = link(store.load_claims(), run_id=args.run_id, now=args.now)

    source, target = args.edge
    matches = [e for e in result.edges
               if e.source_id == source and e.target_id == target]
    if not matches:
        # Declining to explain is an answer. Saying nothing is not.
        print(f"no edge {source} -> {target} in this run", file=sys.stderr)
        return emit(ExplainReport, {
            "found": False, "source": source, "target": target,
            "candidates": sorted({e.source_id for e in result.edges})})
    return emit(ExplainReport, {"found": True,
                                 "edges": [_derivation(e) for e in matches]})


def _measured_row(edge) -> dict:
    from tracekite.services.calibration_tiers import edge_tier
    from tracekite.services.linker.base import load_confidence

    table = load_confidence()
    tier = edge_tier(edge, table)
    if tier is None:
        return {"tier": None,
                "why": "not a priced tier (rollups and structural edges "
                       "derive from priced ones; their measured rows are on "
                       "the underlying INVOKES/EXPOSES edges)"}
    row = ((table.get("measured") or {}).get("rows") or {}).get(tier)
    if not isinstance(row, dict):
        return {"tier": tier, "unmeasured": True}
    out = {"tier": tier, "precision": row.get("precision"),
           "support": row.get("support")}
    if "precision_lo" in row:
        out["interval"] = [row["precision_lo"], row["precision_hi"]]
    return out


def _derivation(edge) -> dict:
    """The full account of why one edge exists.

    Four things, and an edge that cannot supply all four should not have been
    emitted: the rendezvous key two claims agreed on, the resolver that joined
    them, the transforms applied on the way (a gateway prefix stripped, an
    alias resolved, config indirection followed), and the `file:line` on both
    sides. Confidence without those is a number nobody can check.
    """
    extra = getattr(edge, "extra_props", None) or {}
    return {
        "type": edge.type,
        "status": edge.status,
        "confidence": round(edge.confidence, 4),
        # The measured row behind that number, interval included — 1.000 on
        # one labelled edge and on 189 are different claims. An
        # unmeasured tier says so; silence would read as "not applicable".
        "measured": _measured_row(edge),
        # What the two sides met on.
        "rendezvous_key": getattr(edge, "claim_key", "") or "",
        # Who joined them, versioned so a re-run is attributable.
        "resolver": getattr(edge, "detected_by", "") or "",
        # How: the match tier, plus any rewriting applied before the join.
        "transforms": {
            "match_type": getattr(edge, "match_type", "") or "",
            "via": list(extra.get("via", [])),
            "env_scope": getattr(edge, "env_scope", "") or "",
            "path_prefix": extra.get("path_prefix", ""),
        },
        # Where it came from, on both sides.
        "evidence": list(edge.evidence or []),
        "source_repo": getattr(edge, "source_repo_id", "") or "",
        "target_repo": getattr(edge, "target_repo_id", "") or "",
        "cross_repo": bool(getattr(edge, "cross_repo", False)),
        # `declared` (someone wrote it down) vs `matched` (we joined it).
        "origin": getattr(edge, "origin", "") or "",
    }
