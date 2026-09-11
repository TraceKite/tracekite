"""Conservative query-relative completeness evaluation.

Pure: takes metadata and query parameters, returns a CompletenessAssessment.
No I/O, no globals.  The assessment is conservative — ``complete`` is only
True when every factor is accounted for.

A high-confidence positive edge never upgrades the completeness of a
negative result: "we found one consumer with 0.99 confidence" does not
mean "we found every consumer".
"""

from __future__ import annotations

from tracekite.answer import CompletenessAssessment


def evaluate_completeness(
    *,
    expected_repos: list[str],
    analyzed_repos: list[str],
    scan_completed: bool = False,
    parse_failures: int = 0,
    unsupported_idioms: list[str] | None = None,
    unresolved_matching: int = 0,
    result_truncated: bool = False,
    missing_repos: list[str] | None = None,
    coverage_reasons: list[str] | None = None,
) -> CompletenessAssessment:
    """Compute a conservative completeness assessment.

    ``complete`` is True only when:
    - every expected repo was analyzed
    - the scan completed without parse failures
    - no unsupported idioms affect the query
    - no unresolved matching occurred
    - the result was not truncated by a budget

    Any one of these failing prevents completeness.  This is deliberately
    conservative: a gap is a reviewable fact, not a silent absence.
    """
    reasons: list[str] = []
    idioms = unsupported_idioms or []
    missing = missing_repos or []
    observed = coverage_reasons or []
    expected_set = set(expected_repos)
    analyzed_set = set(analyzed_repos)

    unanalyzed = sorted(expected_set - analyzed_set)
    if unanalyzed:
        reasons.extend(unanalyzed)
        missing = missing or unanalyzed

    if not scan_completed:
        reasons.append("scan did not complete")

    if parse_failures > 0:
        reasons.append(f"{parse_failures} parse failure(s)")

    if idioms:
        reasons.append(f"unsupported idioms: {', '.join(idioms)}")

    if unresolved_matching > 0:
        reasons.append(f"{unresolved_matching} unresolved match(es)")

    if result_truncated:
        reasons.append("result truncated by budget")

    for reason in observed:
        if reason not in reasons:
            reasons.append(reason)

    complete = len(reasons) == 0

    return CompletenessAssessment(
        complete=complete,
        coverage_reasons=reasons,
        unsupported_idioms=idioms,
        missing_repos=missing,
        parse_failures=parse_failures,
        unresolved_matching=unresolved_matching,
        scan_completed=scan_completed,
    )
