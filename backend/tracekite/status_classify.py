"""Shared status classification for consumers_of and trace.

Both the facade and the MCP server classify a raw tool result into an
``AnswerStatus``.  Doing it in two places produced a drift bug where trace
called a no-path result between two known nodes ``known_empty`` while
consumers_of called the same shape ``unknown_target``.  This module is the
one place that decision lives.

Pure: takes a result dict, returns ``(AnswerStatus, list[str], str)``.
"""

from __future__ import annotations

from tracekite.answer import AnswerStatus


def classify_consumers(raw: dict) -> tuple[AnswerStatus, list[str], str]:
    """Classify a consumers_of result.

    Returns ``(status, candidates, reason)``.

    - ``found=True`` with consumers → ``PRESENT``
    - ``found=True`` with no consumers → ``KNOWN_EMPTY``
    - ``found=False`` with reason "ambiguous service name" → ``AMBIGUOUS``
    - ``found=False`` otherwise → ``UNKNOWN_TARGET``
    """
    if raw.get("found") is True:
        consumers = raw.get("consumers", [])
        if consumers:
            return AnswerStatus.PRESENT, [], ""
        return AnswerStatus.KNOWN_EMPTY, [], ""
    reason = raw.get("reason", "")
    candidates = raw.get("candidates", [])
    if reason == "ambiguous service name":
        return AnswerStatus.AMBIGUOUS, candidates, reason
    return AnswerStatus.UNKNOWN_TARGET, candidates, reason or "node not in graph"


def classify_trace(raw: dict, known_ids: set[str] | None = None) -> (
        tuple[AnswerStatus, list[str], str]):
    """Classify a trace result.

    Returns ``(status, candidates, reason)``.

    - Paths found → ``PRESENT``
    - No paths, both endpoints known → ``KNOWN_EMPTY``
    - No paths, an endpoint is ambiguous → ``AMBIGUOUS``
    - No paths, an endpoint does not exist → ``UNKNOWN_TARGET``
    """
    if raw.get("found") is True:
        return AnswerStatus.PRESENT, [], ""
    candidates = raw.get("candidates") or {}
    from_cands = candidates.get("from", []) if isinstance(candidates, dict) else []
    to_cands = candidates.get("to", []) if isinstance(candidates, dict) else []
    if from_cands or to_cands:
        return AnswerStatus.AMBIGUOUS, from_cands + to_cands, "ambiguous service name"
    if known_ids is not None:
        from_id = raw.get("from", "")
        to_id = raw.get("to", "")
        if from_id not in known_ids or to_id not in known_ids:
            return AnswerStatus.UNKNOWN_TARGET, [], "endpoint not in graph"
    return AnswerStatus.KNOWN_EMPTY, [], "no path between known nodes"
