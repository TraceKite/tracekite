"""Provider shape changed, consumers not updated.

The failure this catches is quieter than a removed edge: the provider
reshaped an operation between two commits, the consumers kept calling the
old shape, and nothing breaks until the requests do. Both sides are
cited — the old shape at the base commit, every stale call site at the
head — and the head's added operations ride along as context.

What this deliberately does NOT do is pair an old shape to a new one.
"/v1/owners/{id} became /v2/owners/{id}" is an inference about intent;
two shapes that look alike may be unrelated, and a wrong pairing sends
every consumer to migrate to the wrong endpoint. The report states what
is known — this shape existed, it no longer does, these consumers still
call it, these shapes are new — and leaves the pairing to someone who
knows the provider.
"""

from tracekite.utils.canonical import canonicalize_path_template


def _provider_shapes(claims) -> dict[tuple[str, str], list]:
    shapes: dict[tuple[str, str], list] = {}
    for claim in claims:
        if claim.kind == "http" and claim.direction == "provides" \
                and claim.matchable:
            method, _, template = claim.key.partition(":")
            key = (method, canonicalize_path_template(template))
            shapes.setdefault(key, []).append(claim)
    return shapes


def _consumer_calls(claims) -> dict[tuple[str, str], list]:
    calls: dict[tuple[str, str], list] = {}
    for claim in claims:
        if claim.kind == "http" and claim.direction == "consumes" \
                and claim.matchable and claim.key.startswith("httpcall:"):
            rest = claim.key[len("httpcall:"):]
            method, _, template = rest.partition(":")
            key = (method, canonicalize_path_template(template))
            calls.setdefault(key, []).append(claim)
    return calls


def _cite(claim) -> dict:
    return {"repo": claim.repo_id, "evidence": list(claim.evidence or [])}


def contract_drift(base_claims: list, head_claims: list) -> dict:
    """Operations the provider dropped that consumers still call.

    Only shapes with a stale caller are drift: an operation removed along
    with its last consumer is a completed migration, and reporting it
    would teach people to ignore the report.
    """
    base = _provider_shapes(base_claims)
    head = _provider_shapes(head_claims)
    head_calls = _consumer_calls(head_claims)

    drifted = []
    for key in sorted(base.keys() - head.keys()):
        stale = head_calls.get(key, [])
        if not stale:
            continue
        method, template = key
        drifted.append({
            "operation": f"{method} {template}",
            "was_provided_by": [_cite(c) for c in base[key]],
            "still_called_by": [_cite(c) for c in stale],
        })

    return {
        "drifted": drifted,
        # Context, not a pairing: the shapes that appeared at head. Which
        # one replaces a drifted operation is the provider's knowledge.
        "added_operations": [f"{m} {t}"
                             for m, t in sorted(head.keys() - base.keys())],
        "removed_without_callers": [
            f"{m} {t}" for m, t in sorted(base.keys() - head.keys())
            if not head_calls.get((m, t))],
    }
