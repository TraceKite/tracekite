"""Per-resolver reliability from labelled evidence.

Constants are derived, not chosen: every served tier value must sit at or
below its evidence ceilings — the 95% Wilson upper bound on the tier's own
pooled labels, and on its resolver's. `tools/calibrate.py` fails when a
constant exceeds either, and names the derived value to adopt, so a human
can no longer keep a number the labels contradict.

A ceiling rather than a point estimate, deliberately. Serving the Wilson
LOWER bound was rejected: at the label volumes this project has —
architecture §11.10 names label availability, not compute, as
calibration's ceiling — a lower bound tracks sample size, not resolver
quality, and would demote every tier below the floor. The upper bound has
the property that matters: clean evidence leaves the design prior
standing (recorded as `prior`, visibly unproven), while a single labelled
false positive drags the ceiling under the constant and the constant must
follow it down. Volume alone never inflates a number; a wrong edge always
lowers one.

Labels pool from two sources: the calibration estates' measured rows, and
operator review decisions — a promote is a TP, a reject an FP. A
review that names its tier sharpens that tier and its resolver; one that
does not pools globally, reported but capping nothing, because an
unattributed mistake cannot fairly indict a specific tier.
"""

import re

from evigraph.services.calibration_tiers import flat_sections
from evigraph.services.linker.confidence_math import wilson_interval

_TIER = re.compile(r"^(r\d+)\.(\w+)$")


def _bump(pool: dict, key: str, tp: int = 0, fp: int = 0) -> None:
    entry = pool.setdefault(key, {"tp": 0, "fp": 0})
    entry["tp"] += tp
    entry["fp"] += fp


def pool_labels(measured_rows: list[dict], labels: dict) -> dict:
    """Pooled (tp, fp) per tier, per resolver, and globally.

    ``measured_rows`` is the calibrate table (one dict per tier with
    ``tier``, ``support``, ``recall``, ``fp``); tp is recovered as
    recall x support because support counts expected edges (tp + fn).
    ``labels`` is ``review_labels()`` output; entries whose ``tier``
    matches ``rN.name`` join that tier's pool, the rest only the global
    one, tallied under ``unattributed`` so they cannot vanish.
    """
    pools = {"tier": {}, "resolver": {}, "global": {"tp": 0, "fp": 0},
             "unattributed": {"tp": 0, "fp": 0}}
    for row in measured_rows:
        tp = round(float(row.get("recall", 0.0)) * int(row.get("support", 0)))
        fp = int(row.get("fp", 0))
        match = _TIER.match(row["tier"])
        if match:
            _bump(pools["tier"], row["tier"], tp, fp)
            _bump(pools["resolver"], match.group(1), tp, fp)
        _bump(pools, "global", tp, fp)

    for verdict, field in (("tp", "tp"), ("fp", "fp")):
        for entry in labels.get(verdict, []):
            counts = {field: 1}
            match = _TIER.match(entry.get("tier") or "")
            if match:
                _bump(pools["tier"], match.group(0), **counts)
                _bump(pools["resolver"], match.group(1), **counts)
            else:
                _bump(pools, "unattributed", **counts)
            _bump(pools, "global", **counts)
    return pools


def _ceiling(pool: dict | None) -> float:
    """Wilson 95% upper bound on precision; 1.0 when nothing is labelled.

    Trials are labelled decisions about served edges (tp + fp), so an
    unlabelled tier is unbounded — no data bounds nothing — and the row
    records that as basis `prior` rather than pretending it was measured.
    """
    if not pool:
        return 1.0
    return wilson_interval(pool["tp"], pool["tp"] + pool["fp"])[1]


def derive_constants(served_table: dict, measured_rows: list[dict],
                     labels: dict) -> dict:
    """Every flat served tier with its evidence ceilings and derived value.

    ``derived = min(served, tier ceiling, resolver ceiling)`` — the gate in
    calibrate demands served == derived, so a served value above either
    ceiling is the failure, and the derived value is the number to adopt.
    """
    pools = pool_labels(measured_rows, labels)
    rows = []
    for section in flat_sections(served_table):
        tiers = served_table.get(section)
        if not isinstance(tiers, dict):
            continue
        for tier, served in sorted(tiers.items()):
            if not isinstance(served, (int, float)) or isinstance(served, bool):
                continue
            key = f"{section}.{tier}"
            tier_pool = pools["tier"].get(key)
            tier_hi = _ceiling(tier_pool)
            resolver_hi = _ceiling(pools["resolver"].get(section))
            derived = round(min(float(served), tier_hi, resolver_hi), 4)
            if tier_hi < float(served):
                basis = "tier_evidence"
            elif resolver_hi < float(served):
                basis = "resolver_evidence"
            else:
                basis = "prior"
            rows.append({"tier": key, "served": float(served),
                         "derived": derived, "basis": basis,
                         "ceiling_tier": tier_hi,
                         "ceiling_resolver": resolver_hi,
                         "tp": (tier_pool or {}).get("tp", 0),
                         "fp": (tier_pool or {}).get("fp", 0)})
    return {"rows": sorted(rows, key=lambda r: r["tier"]),
            "unattributed": dict(pools["unattributed"]),
            "global": dict(pools["global"])}


def derived_block_lines(derivation: dict) -> list[str]:
    """The `derived:` section written beside `measured:` in confidence.yml."""
    unattributed = derivation["unattributed"]
    lines = ["derived:",
             f"  unattributed_labels: {{tp: {unattributed['tp']}, "
             f"fp: {unattributed['fp']}}}",
             "  rows:"]
    for row in derivation["rows"]:
        lines.append(
            f"    {row['tier']}: {{served: {row['served']}, "
            f"derived: {row['derived']}, basis: {row['basis']}, "
            f"tp: {row['tp']}, fp: {row['fp']}}}")
    return lines
