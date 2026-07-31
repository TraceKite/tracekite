"""Absence is recorded, not implied.

"This repository has no Kafka producers" and "we could not parse the files
that would have had them" produce the same empty result today, and they are
opposite answers. One says a change is safe; the other says nobody knows.

So a scan states what it looked for. Absence is only evidence where the search
was complete, and this makes that condition explicit rather than leaving a
reader to assume it — which is the same rule as decline-don't-guess, applied
to the scan instead of the join.
"""

from dataclasses import dataclass, field

# Every kind a parser can emit. A kind missing from this list would be
# reported as "never absent" — it would simply never appear, which is exactly
# the implied absence this module exists to remove.
KNOWN_CLAIM_KINDS = (
    "svcname", "http", "route", "cfgdef", "cfgread", "grpcstub", "grpcsvc",
    "topic", "owner", "image", "library", "dataset", "agent", "graphql",
    "gateway", "env_host", "publish", "subscribe", "migration", "catalog",
    "observability",
)


@dataclass
class Absence:
    """What a scan looked for, and how far it got."""

    complete: bool = False
    incomplete_because: list[str] = field(default_factory=list)
    kinds_found: list[str] = field(default_factory=list)
    kinds_absent: list[str] = field(default_factory=list)

    @property
    def absence_is_evidence(self) -> bool:
        """Whether "not found" may be read as "not there".

        The whole point. A caller acting on `kinds_absent` without checking
        this is treating an unparsed file as an empty one.
        """
        return self.complete

    def as_dict(self) -> dict:
        return {"complete": self.complete,
                "incomplete_because": list(self.incomplete_because),
                "kinds_found": list(self.kinds_found),
                "kinds_absent": list(self.kinds_absent),
                "absence_is_evidence": self.absence_is_evidence}


def absence_report(sink) -> Absence:
    """What this scan can and cannot say was not there.

    Incompleteness is named per cause rather than as a single flag: a
    reviewer deciding whether to trust an absence needs to know it was a
    parse error in Kotlin rather than a size cap in YAML, because those
    suggest different follow-ups.
    """
    reasons: list[str] = []

    for language, counters in sorted(sink.coverage.items()):
        errors = counters.get("parse_errors", 0)
        skipped = counters.get("files_skipped_large", 0)
        timeouts = counters.get("parse_timeouts", 0)
        if errors:
            reasons.append(f"{language}: {errors} file(s) failed to parse")
        if skipped:
            reasons.append(f"{language}: {skipped} file(s) over the size cap")
        if timeouts:
            reasons.append(f"{language}: {timeouts} parse timeout(s)")
        if counters.get("tier") == "none" and counters.get("files_seen"):
            reasons.append(
                f"{language}: seen but unsupported, so nothing was extracted")

    # Caps and unfetched submodules are whole-repo blinds: a truncated scan
    # cannot claim anything about what it never reached.
    for what, count in sorted(getattr(sink, "capped", {}).items()):
        reasons.append(f"{count} {what} dropped by a resource cap")
    for path in sorted(getattr(sink, "unfetched_submodules", []) or []):
        reasons.append(f"submodule {path} was never fetched")

    found = sorted(k for k, n in sink.claims.items()
                   if n and not k.startswith("_"))
    absent = sorted(k for k in KNOWN_CLAIM_KINDS if k not in found)

    return Absence(complete=not reasons, incomplete_because=reasons,
                   kinds_found=found, kinds_absent=absent)
