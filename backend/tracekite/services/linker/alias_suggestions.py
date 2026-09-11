"""Alias suggestions mined from declines — surfaced, never applied.

An internal-looking consumer hint that matched no service is this
project's most common recall gap, and the fix is almost always one line
in `service_aliases.yml`. This module drafts that line: it pairs each
unmatched hint with the known services it would equal under a small set
of NAMED transforms (separators, a strength suffix, a DNS label), each
suggestion citing the call sites that produced it.

Nothing here writes a file, changes the alias table, or emits an edge.
An alias is an operator assertion of identity; guessed identity is an
invented edge one hop removed, so the machine drafts and the human
decides — the decline stays a decline until someone signs it.
"""

from tracekite.services.linker.base import LinkContext
from tracekite.services.linker.vendors import classify, load_vendors, looks_external
from tracekite.utils.canonical import squash_separators

# One transform each way, never chained twice: "users-svc" ~ "users" is a
# spelling, "users-svc-api" ~ "user" is a guess.
_SUFFIXES = ("service", "server", "svc", "srv", "api", "app")

_MAX_SUGGESTIONS = 50   # a review queue, not a landfill
_MAX_CANDIDATES = 3     # matching more services than this is noise
_MAX_EVIDENCE = 3


def _strip_suffix(squashed: str) -> str:
    for suffix in _SUFFIXES:
        if squashed.endswith(suffix) and len(squashed) > len(suffix):
            return squashed[: -len(suffix)]
    return squashed


def _forms(name: str) -> dict[str, str]:
    """The comparable forms of a name, keyed by the rule that made each."""
    squashed = squash_separators(name.partition(":")[2] or name)
    forms = {"separators": squashed}
    stripped = _strip_suffix(squashed)
    if stripped != squashed:
        forms["suffix"] = stripped
    label = name.split(".", 1)[0]
    if label and label != name:
        forms["dns_label"] = _strip_suffix(squash_separators(label))
    return forms


def _candidates(hint: str, targets: dict[str, str]) -> list[dict]:
    matches: dict[str, str] = {}
    for hint_rule, hint_form in _forms(hint).items():
        for target_form, target in targets.items():
            if hint_form == target_form and target not in matches:
                matches[target] = hint_rule
    return [{"service": t, "rule": r} for t, r in sorted(matches.items())]


def suggest_aliases(claims: list, services: list, aliases: dict) -> dict:
    """Unmatched consumer hints paired with the services they may mean.

    ``services`` is a LinkResult's service list — the run's own view of
    what exists — and ``aliases`` the operator table, reused through
    LinkContext so a hint an existing alias already covers is never
    re-suggested. Every non-suggestion is counted, not dropped.
    """
    ctx = LinkContext("alias-suggest", {}, aliases)
    known = {ctx.canon(spec.name) for spec in services}
    targets: dict[str, str] = {}
    for spec in sorted(services, key=lambda s: s.name):
        for form in _forms(spec.name).values():
            targets.setdefault(form, spec.name)

    vendors = load_vendors()
    sites: dict[str, list[str]] = {}
    declined = {"already_known": 0, "external_vendor": 0,
                "external_unknown": 0, "no_candidate": 0,
                "too_ambiguous": 0, "over_limit": 0}
    for claim in claims:
        hint = (claim.service_hint or "").strip()
        if not hint or claim.direction != "consumes":
            continue
        if ctx.canon(hint) in known:
            declined["already_known"] += 1
            continue
        if looks_external(hint):
            declined["external_vendor" if classify(hint, vendors)
                     else "external_unknown"] += 1
            continue
        sites.setdefault(hint.lower(), []).extend(claim.evidence or [])

    suggestions = []
    for hint in sorted(sites):
        candidates = _candidates(hint, targets)
        if not candidates:
            declined["no_candidate"] += 1
            continue
        if len(candidates) > _MAX_CANDIDATES:
            declined["too_ambiguous"] += 1
            continue
        if len(suggestions) >= _MAX_SUGGESTIONS:
            declined["over_limit"] += 1
            continue
        suggestions.append({
            "alias": hint,
            "candidates": candidates,
            "call_sites": len(sites[hint]),
            "evidence": sorted(sites[hint])[:_MAX_EVIDENCE],
            "yaml": f"{candidates[0]['service']}:\n"
                    f"  aliases: [\"{hint}\"]",
        })
    return {"suggestions": suggestions, "declined": declined}
