"""Wrap MCP tool results into the full AnswerEnvelope contract.

The MCP server returns raw tool dicts (``found``, ``consumers``, etc.).
Old clients read those top-level fields directly.  This module wraps the
raw result into an ``AnswerEnvelope`` while preserving the top-level
fields so neither side breaks: the envelope fields are added alongside
the existing ones, not in their place.
"""

from __future__ import annotations

from tracekite.answer import (
    ANSWER_VERSION,
    AnswerEnvelope,
    AnswerStatus,
    CompletenessAssessment,
    FreshnessState,
    QueryScope,
    SnapshotIdentity,
    TruncationInfo,
)
from tracekite.completeness import evaluate_completeness
from tracekite.scan_meta import ScanMeta
from tracekite.status_classify import classify_consumers, classify_trace


def _classify_for_envelope(tool_name: str, answer: dict,
                           known_ids: set[str] | None = None
                           ) -> tuple[AnswerStatus, list[str], str]:
    """Dispatch to the shared classifier for the tool."""
    if tool_name == "consumers_of":
        return classify_consumers(answer)
    if tool_name == "trace":
        return classify_trace(answer, known_ids)
    if answer.get("found") is True:
        has_results = bool(
            answer.get("consumers") or answer.get("paths")
            or answer.get("services") or answer.get("contracts"))
        return (AnswerStatus.PRESENT if has_results
                else AnswerStatus.KNOWN_EMPTY), [], ""
    if answer.get("found") is False:
        return AnswerStatus.UNKNOWN_TARGET, [], answer.get("reason", "")
    return AnswerStatus.PRESENT, [], ""


def wrap_answer(answer: dict, tool_name: str, args: dict,
                snapshot: SnapshotIdentity,
                known_ids: set[str] | None = None,
                scan_meta: ScanMeta | None = None,
                expected_repos: list[str] | None = None) -> dict:
    """Merge answer context into a tool result for versioned responses.

    Existing fields (``found``, ``consumers``, etc.) stay at the top level
    so old clients keep working.  The full ``AnswerEnvelope`` shape —
    ``answer_version``, ``status``, ``snapshot``, ``scope``,
    ``completeness``, ``freshness``, ``result``, ``candidates``,
    ``reason`` — is added alongside, and the whole payload validates as
    ``AnswerEnvelope(**payload)``.
    """
    status, candidates, reason = _classify_for_envelope(
        tool_name, answer, known_ids)

    expected = sorted(set(expected_repos or []))
    analyzed = expected
    if tool_name == "services":
        analyzed = sorted({
            repo_id
            for service in answer.get("services", [])
            for repo_id in service.get("repos", [])
        })
    scan_completed = scan_meta is not None and all(
        meta.scan_completed for meta in scan_meta.repos.values())
    comp = evaluate_completeness(
        expected_repos=expected,
        analyzed_repos=analyzed,
        scan_completed=scan_completed,
        parse_failures=(
            scan_meta.total_parse_failures if scan_meta is not None else 0
        ),
        result_truncated=(
            scan_meta.any_truncated if scan_meta is not None else False
        ),
        coverage_reasons=(
            scan_meta.absence_reasons() if scan_meta is not None else []
        ),
    )
    truncation = None
    if scan_meta is not None:
        from tracekite import engine_config

        budget = None
        if scan_meta.cap_types == {"files"}:
            budget = engine_config.get_config().max_files_per_repo
        elif scan_meta.cap_types == {"claims"}:
            budget = engine_config.get_config().max_claims_per_repo
        truncation = scan_meta.truncation_info(budget=budget)
    scope = QueryScope(
        query_kind=tool_name,
        parameters=dict(args),
        expected_repos=expected,
        analyzed_repos=analyzed,
        truncation=truncation or TruncationInfo(),
    )
    envelope = AnswerEnvelope(
        answer_version=ANSWER_VERSION,
        status=status,
        snapshot=snapshot,
        scope=scope,
        completeness=comp,
        freshness=FreshnessState.UNKNOWN,
        result=answer,
        candidates=candidates,
        reason=reason,
    )
    dumped = envelope.model_dump()
    # Preserve the top-level fields old clients read.  The envelope's
    # ``result`` already carries them, but some clients index the top
    # level directly, so they stay there too.
    for key, value in answer.items():
        dumped[key] = value
    dumped["answer_version"] = ANSWER_VERSION
    dumped["status"] = status.value
    dumped["snapshot"] = {
        "repos": [r.model_dump() for r in snapshot.repos],
        "engine_version": snapshot.engine_version,
        "config_digest": snapshot.config_digest,
    }
    dumped["completeness"] = comp.model_dump()
    dumped["completeness"]["safe_to_delete"] = False
    dumped["freshness"] = FreshnessState.UNKNOWN.value
    dumped["scope"] = scope.model_dump()
    return dumped
