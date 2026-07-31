"""Confidence as an interval, and how it compounds over a path.

`0.94 ± 0.02` is honest; `0.94` is not — a precision of 1.000 measured on
one labelled edge and one measured on 189 are different claims, and only
the interval says so. The Wilson score is used rather than the normal
approximation because the supports here are tiny (1–5 per tier) and the
proportions sit at the boundary, exactly where the normal interval
collapses to a lying `[1.0, 1.0]`.

Paths compound. A 6-hop trace at 0.9 per hop is not a 0.9 path; under the
independence assumption it is a 0.53 path, and pretending otherwise makes
long chains look as trustworthy as direct calls. Independence is an
assumption, stated here once: correlated evidence along a path (two hops
derived from the same manifest) makes the true value *higher* than the
product, so the product is the conservative bound — the direction that
never overstates.
"""

import math

# 95% two-sided. One constant, not a parameter: every interval this project
# serves must mean the same thing, or two tiers' bounds cannot be compared.
_Z = 1.959963984540054


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    """The 95% Wilson score interval for a proportion.

    Returns (0.0, 1.0) for zero trials: no data bounds nothing, and any
    narrower answer would be an invented measurement.
    """
    if trials <= 0:
        return 0.0, 1.0
    if not 0 <= successes <= trials:
        raise ValueError(f"successes {successes} outside 0..{trials}")

    p = successes / trials
    z2 = _Z * _Z
    denom = 1 + z2 / trials
    centre = (p + z2 / (2 * trials)) / denom
    spread = (_Z * math.sqrt(p * (1 - p) / trials
                             + z2 / (4 * trials * trials))) / denom
    return round(max(0.0, centre - spread), 4), \
        round(min(1.0, centre + spread), 4)


def path_confidence(hops: list) -> dict:
    """How sure the whole path is, from how sure each hop is.

    Each hop is a float, or a `(point, lo, hi)` triple when the edge
    carries an interval. `weakest_hop` is reported beside the product
    because they answer different questions: the product says how much to
    trust the chain, the weakest hop says where to look first.
    """
    if not hops:
        # Zero hops is a question about a path that does not exist;
        # returning confidence 1.0 for it would bless the empty chain.
        return {"hops": 0, "compounded": 0.0, "lo": 0.0, "hi": 0.0,
                "weakest_hop": 0.0}

    point = lo = hi = 1.0
    weakest = None
    for hop in hops:
        if isinstance(hop, (int, float)):
            p, hop_lo, hop_hi = float(hop), float(hop), float(hop)
        else:
            p, hop_lo, hop_hi = (float(v) for v in hop)
        point *= p
        lo *= hop_lo
        hi *= hop_hi
        weakest = p if weakest is None else min(weakest, p)

    return {"hops": len(hops), "compounded": round(point, 4),
            "lo": round(lo, 4), "hi": round(hi, 4),
            "weakest_hop": round(weakest, 4)}
