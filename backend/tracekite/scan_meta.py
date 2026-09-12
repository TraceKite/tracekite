"""Collect scan-level metadata for completeness and truncation.

The facade scans repositories and links them once.  The scan produces an
``IngestSink`` per repo that carries caps, absence, and parse coverage —
all the facts that determine whether a negative result is evidence or a
gap.  This module distils those sinks into the inputs
``evaluate_completeness`` and ``TruncationInfo`` consume, so the facade
does not reach into sink internals directly.

Pure: takes sink data, returns data.  No I/O.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from tracekite.answer import TruncationInfo


@dataclass
class RepoScanMeta:
    """Per-repository scan facts that affect completeness."""

    repo_id: str
    capped: dict[str, int] = field(default_factory=dict)
    absence_complete: bool = True
    absence_reasons: list[str] = field(default_factory=list)
    parse_failures: int = 0
    budgets: dict[str, int] = field(default_factory=dict)
    metadata_complete: bool = True

    @property
    def scan_completed(self) -> bool:
        """A returned sink proves the scan ran; caps affect completeness."""
        return self.metadata_complete

    @property
    def truncated(self) -> bool:
        return bool(self.capped)

    @property
    def omitted_count(self) -> int:
        return sum(self.capped.values())


@dataclass
class ScanMeta:
    """Aggregated scan metadata across all repos."""

    repos: dict[str, RepoScanMeta] = field(default_factory=dict)

    def add(self, meta: RepoScanMeta) -> None:
        self.repos[meta.repo_id] = meta

    @property
    def any_truncated(self) -> bool:
        return any(m.truncated for m in self.repos.values())

    @property
    def total_omitted(self) -> int:
        return sum(m.omitted_count for m in self.repos.values())

    @property
    def cap_types(self) -> set[str]:
        return {cap for meta in self.repos.values() for cap in meta.capped}

    @property
    def total_parse_failures(self) -> int:
        return sum(m.parse_failures for m in self.repos.values())

    def absence_reasons(self) -> list[str]:
        reasons: list[str] = []
        for meta in sorted(self.repos.values(), key=lambda m: m.repo_id):
            for reason in meta.absence_reasons:
                qualified = f"{meta.repo_id}: {reason}"
                if qualified not in reasons:
                    reasons.append(qualified)
        return reasons

    def truncation_info(self, budget: int | None = None) -> TruncationInfo:
        if not self.any_truncated:
            return TruncationInfo()
        cap_types = sorted(self.cap_types)
        if budget is None and len(cap_types) == 1:
            values = {
                meta.budgets[cap_types[0]]
                for meta in self.repos.values()
                if cap_types[0] in meta.budgets
            }
            if len(values) == 1:
                budget = values.pop()
        return TruncationInfo(
            truncated=True,
            reason="scan truncated by resource cap(s): " + ", ".join(cap_types),
            omitted_count=self.total_omitted,
            budget=budget,
        )


def repo_scan_meta_from_sink(
    sink, repo_id: str, budgets: dict[str, int] | None = None
) -> RepoScanMeta:
    """Build ``RepoScanMeta`` from an ``IngestSink``.

    Reads ``capped``, ``absence``, and per-language parse error counts —
    the fields the scan itself populates (see ``scan.py`` and ``absence.py``).
    """
    capped = dict(getattr(sink, "capped", {}) or {})
    absence = getattr(sink, "absence", {}) or {}
    absence_complete = bool(absence.get("complete", True))
    absence_reasons = list(absence.get("incomplete_because", []) or [])

    parse_failures = 0
    for counters in getattr(sink, "coverage", {}).values():
        parse_failures += counters.get("parse_errors", 0)

    return RepoScanMeta(
        repo_id=repo_id,
        capped=capped,
        absence_complete=absence_complete,
        absence_reasons=absence_reasons,
        parse_failures=parse_failures,
        budgets=dict(budgets or {}),
    )


def repo_scan_meta_from_artifact(meta: dict, repo_id: str) -> RepoScanMeta:
    """Recover scan coverage retained in a ``.tracekite`` artifact."""
    capped = {
        str(key): int(value)
        for key, value in (meta.get("capped") or {}).items()
    }
    absence = meta.get("absence") or {}
    reasons = list(absence.get("incomplete_because", []) or [])
    absence_complete = bool(absence.get("complete", False))
    for path in sorted(meta.get("unfetched_submodules") or []):
        reason = f"submodule {path} was never fetched"
        if reason not in reasons:
            reasons.append(reason)
    if not absence_complete and not reasons:
        reasons.append("artifact absence metadata is incomplete")

    parse_failures = 0
    for counters in (meta.get("coverage") or {}).values():
        if isinstance(counters, dict):
            parse_failures += int(counters.get("parse_errors", 0) or 0)

    producer = meta.get("producer") or {}
    budgets = {}
    if isinstance(producer, dict):
        for cap in ("files", "claims"):
            value = producer.get(f"max_{cap}_per_repo")
            if value is not None:
                budgets[cap] = int(value)
    metadata_complete = all(
        field in meta
        for field in ("coverage", "capped", "absence", "unfetched_submodules")
    )
    return RepoScanMeta(
        repo_id=repo_id,
        capped=capped,
        absence_complete=absence_complete,
        absence_reasons=reasons,
        parse_failures=parse_failures,
        budgets=budgets,
        metadata_complete=metadata_complete,
    )


def config_digest(config) -> str:
    """A deterministic fingerprint of every graph-affecting config input.

    This includes runtime scan limits and the versioned control-plane files
    used by the linker. The HMAC key contributes only its presence, never its
    value, so snapshot identity cannot become a secret side channel.

    The HMAC key itself is never included in the digest. Whether a key is set
    is enough to distinguish redacted from unredacted claims.
    """
    import hashlib
    import json

    runtime = json.dumps({
        "max_files_per_repo": config.max_files_per_repo,
        "max_claims_per_repo": config.max_claims_per_repo,
        "parse_file_cap_bytes": config.parse_file_cap_bytes,
        "parse_timeout_s": config.parse_timeout_s,
        "has_graph_hmac_key": bool(config.graph_hmac_key),
    }, sort_keys=True)
    digest = hashlib.sha256()
    digest.update(runtime.encode())
    config_dir = config.config_dir
    if os.path.isdir(config_dir):
        for root, dirs, names in os.walk(config_dir):
            dirs.sort()
            for name in sorted(names):
                path = os.path.join(root, name)
                if not os.path.isfile(path):
                    continue
                relative = os.path.relpath(path, config_dir)
                digest.update(relative.encode())
                try:
                    with open(path, "rb") as handle:
                        digest.update(handle.read())
                except OSError:
                    digest.update(b"<unreadable>")
    return digest.hexdigest()[:16]
