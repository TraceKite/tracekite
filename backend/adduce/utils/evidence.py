"""The evidence-string grammar, interpreted in exactly one place.

Architecture §3.1 is normative: evidence IS the string `path/to/file.py:42`
— compact, diffable, and stable in artifacts. What was scattered was its
interpretation: five modules each re-split it inline. This module owns the
grammar (`path`, `path:42`, `path:42-45`) so spans are DERIVED at the
boundaries that need structure — deep links, re-verification — and never
stored. Same precedent as G1: the roadmap asked for spans to replace
strings everywhere; §3.1 says the string is the record, so the divergence
ships as derivation.

Two functions, two jobs, deliberately not one:

- `evidence_path()` is identity-critical. Claim ids hash it, so its
  semantics are frozen to the historical `rsplit(":", 1)[0]` — changing
  what it returns for ANY input ever emitted churns every claim id in
  every stored artifact.
- `parse_evidence()` is the span-aware reading for display and
  verification. It refuses to invent a line: a tail that is not a number
  or a range is part of the file name, not a location.
"""

import re
from dataclasses import dataclass

_LINES = re.compile(r"^(\d+)(?:-(\d+))?$")


@dataclass(frozen=True)
class EvidenceSpan:
    file: str
    line_start: int | None = None
    line_end: int | None = None

    def as_dict(self, commit: str = "") -> dict:
        span = {"file": self.file, "line_start": self.line_start,
                "line_end": self.line_end}
        if commit:
            span["commit"] = commit
        return span


def evidence_path(evidence: str) -> str:
    """The path half, with the exact semantics claim ids were hashed under.

    Frozen: `rsplit(":", 1)[0]`. Do not make this span-aware — on a
    malformed tail it would return a different string than every already
    stored claim id was derived from.
    """
    return evidence.rsplit(":", 1)[0]


def parse_evidence(evidence: str) -> EvidenceSpan:
    """`path`, `path:42` or `path:42-45` as a span; never invents a line."""
    path, sep, tail = evidence.rpartition(":")
    match = _LINES.match(tail) if sep else None
    if not match:
        return EvidenceSpan(file=evidence)
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if end < start:
        return EvidenceSpan(file=evidence)
    return EvidenceSpan(file=path, line_start=start, line_end=end)


def format_evidence(span: EvidenceSpan) -> str:
    """The canonical string for a span — `parse_evidence` round-trips it."""
    if span.line_start is None:
        return span.file
    if span.line_end and span.line_end != span.line_start:
        return f"{span.file}:{span.line_start}-{span.line_end}"
    return f"{span.file}:{span.line_start}"


def as_spans(evidence: list, commit: str = "") -> list[dict]:
    """Evidence strings as structured spans, for boundaries that deep-link."""
    return [parse_evidence(e).as_dict(commit) for e in evidence or []]
