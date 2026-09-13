"""The versioned intelligence-answer contract.

Every MCP tool response and, later, every facade call is wrapped in an
``AnswerEnvelope`` that carries the same scope, uncertainty and identity
semantics regardless of which tool produced it.  A host that reads one
answer reads them all.

**Compatibility policy.** ``ANSWER_VERSION`` is semantic.  A field added
with a default is a minor bump — old readers keep working.  Removing a
field, renaming one, narrowing a type, or changing what a value *means* is
a **major** bump, because each silently breaks a reader still doing the old
thing.  When in doubt it is major: a consumer that crashes is better off
than one that misreads.

This contract is distinct from ``wire.WIRE_VERSION`` (the CLI payload
schema).  The two version independently because they serve different
consumers: the CLI pipes to ``jq`` and CI differs; the answer envelope
serves agents and framework integrations.  Neither silently rewrites the
other's frozen schema.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

ANSWER_VERSION = "1.0.0"
ENGINE_VERSION = "2.0.0"
CONFIG_VERSION = "1.0"


class AnswerStatus(str, Enum):
    """What the answer says about the target, not about the world.

    The distinction matters: ``known_empty`` is a measured result inside a
    named snapshot, not a universal permission.  ``unknown_target`` means
    the graph has no record of the thing asked about.  ``ambiguous`` means
    the name matched more than one node and the resolver declined.
    ``unavailable`` means the query itself failed.  None of these is
    "safe to delete".
    """

    PRESENT = "present"
    KNOWN_EMPTY = "known_empty"
    UNKNOWN_TARGET = "unknown_target"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


class FreshnessState(str, Enum):
    """Whether the snapshot still describes the source a host is about to act on."""

    CURRENT = "current"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"
    UNKNOWN = "unknown"


class RepoRevision(BaseModel):
    """Per-repository source identity inside a snapshot.

    ``head_sha`` and ``content_digest`` are independently optional because a
    directory scan may have no Git history (``unversioned``) or a dirty tree
    whose working-copy digest does not match any commit.  Artifact inputs
    also carry their content digest and producer metadata.  An empty string
    is not a valid revision; ``None`` means "unknown", and unknown stays
    unknown — it is never filled with a placeholder.
    """

    repo_id: str
    head_sha: str | None = None
    content_digest: str | None = None
    dirty: bool = False
    unversioned: bool = False
    producer: dict[str, Any] = Field(default_factory=dict)

    @field_validator("head_sha", "content_digest")
    @classmethod
    def reject_empty_string(cls, v: str | None) -> str | None:
        """An empty string is not a revision; None means unknown.

        Unknown revisions must stay unknown — a placeholder would let a
        host mistake "we don't know" for "we know it's blank".
        """
        if v == "":
            return None
        return v


class SnapshotIdentity(BaseModel):
    """Reproducible identity for the source state behind an answer."""

    repos: list[RepoRevision] = Field(default_factory=list)
    engine_version: str = ""
    config_version: str = ""
    config_digest: str | None = None

    def canonical_digest(self) -> str:
        """A stable fingerprint of the inputs that produced this answer.

        This identifies declared snapshot inputs, not a query or its answer.
        Query kind, scope, parameters and limits need a separate identity.
        Observational timing is excluded; equal digests do not establish
        source completeness, freshness or semantic correctness.
        """
        import hashlib
        import json

        payload = json.dumps(
            {
                "repos": [r.model_dump() for r in sorted(
                    self.repos, key=lambda r: r.repo_id)],
                "engine_version": self.engine_version,
                "config_version": self.config_version,
                "config_digest": self.config_digest,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class TruncationInfo(BaseModel):
    """When a result was cut short by a budget, not by absence."""

    truncated: bool = False
    reason: str = ""
    omitted_count: int = 0
    budget: int | None = None


class QueryScope(BaseModel):
    """What was asked and what limitations apply to the answer."""

    query_kind: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_repos: list[str] = Field(default_factory=list)
    analyzed_repos: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, int] = Field(default_factory=dict)
    truncation: TruncationInfo = Field(default_factory=TruncationInfo)


class CompletenessAssessment(BaseModel):
    """What the answer covers and, critically, what it does not.

    ``complete`` is conservative: it is only ``True`` when every factor —
    declared scope, supported extraction patterns, parse success, resolved
    matching and result limits — is accounted for.  A high-confidence
    positive edge never upgrades the completeness of a negative result.
    """

    complete: bool = False
    coverage_reasons: list[str] = Field(default_factory=list)
    unsupported_idioms: list[str] = Field(default_factory=list)
    missing_repos: list[str] = Field(default_factory=list)
    parse_failures: int = 0
    unresolved_matching: int = 0
    scan_completed: bool = False

    @property
    def safe_to_delete(self) -> bool:
        """Never.  An empty or incomplete result is not a deletion licence.

        This property exists so that a host cannot accidentally read
        ``known_empty`` as permission.  It is always ``False`` — the only
        correct answer when the question is "can I remove this code?".
        """
        return False


class AnswerEnvelope(BaseModel):
    """The versioned wrapper around every intelligence answer.

    A host receives ``status``, ``snapshot``, ``scope``, ``completeness``
    and ``freshness`` on every response, alongside the tool-specific
    ``result``.  When ``status`` is not ``PRESENT``, ``result`` may be
    empty and ``candidates`` / ``reason`` carry the context a host needs
    to distinguish "nobody depends on this" from "we don't know this node".
    """

    answer_version: str = ANSWER_VERSION
    status: AnswerStatus
    snapshot: SnapshotIdentity
    scope: QueryScope
    completeness: CompletenessAssessment
    freshness: FreshnessState = FreshnessState.UNKNOWN
    result: dict[str, Any] = Field(default_factory=dict)
    candidates: list[str] = Field(default_factory=list)
    reason: str = ""

    def to_mcp_content(self) -> list[dict[str, str]]:
        """Serialize as MCP ``content`` text blocks."""
        import json

        return [{"type": "text", "text": json.dumps(
            self.model_dump(), sort_keys=True)}]
