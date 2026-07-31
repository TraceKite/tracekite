"""Internal graph data models: nodes, edges with provenance envelope, claims, jobs."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

ENVELOPE_VERSION = 1

# Envelope defaults applied by the reader layer for the lite tier (design §5.4).
LITE_DEFAULTS = {"confidence": 1.0, "origin": "extracted", "created_by": "ingestion",
                 "status": "active", "cross_repo": False}

ORIGINS = ("extracted", "inferred", "matched", "declared", "manual")

# Repo lifecycle state machine (design §6.3); transitions written only by the job system.
REPO_STATES = ("queued", "cloning", "parsing", "writing", "ingested",
               "linking", "linked", "failed_clean", "failed_partial")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GraphNode:
    """A Layer-0 node (repo-namespaced, :GraphNode + type label)."""
    id: str
    repo_id: str
    type: str
    name: str
    label: str
    path: Optional[str] = None
    language: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    signature: Optional[str] = None
    summary: Optional[str] = None
    symbol_uid: Optional[str] = None
    extra_props: dict = field(default_factory=dict)  # promoted, indexable scalars
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_neo4j_props(self) -> dict:
        props = {
            "id": self.id,
            "repo_id": self.repo_id,
            "type": self.type,
            "name": self.name,
            "label": self.label,
            "path": self.path,
            "language": self.language,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "summary": self.summary,
            "symbol_uid": self.symbol_uid,
            "metadata": json.dumps(self.metadata) if self.metadata else "{}",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        for key, value in self.extra_props.items():
            if key not in props and _is_scalar(value):
                props[key] = value
        return props


def _is_scalar(value) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None or (
        isinstance(value, list) and all(isinstance(v, (str, int, float, bool)) for v in value)
    )


@dataclass
class GraphEdge:
    """A relationship carrying the provenance envelope (full or lite tier)."""
    source_id: str
    target_id: str
    repo_id: str
    type: str
    label: str = ""
    weight: int = 1
    confidence: float = 1.0
    origin: str = "extracted"
    detected_by: str = ""
    match_type: str = ""
    evidence: list[str] = field(default_factory=list)  # "path:line", first is primary
    source_repo_id: str = ""
    target_repo_id: str = ""
    cross_repo: bool = False
    created_by: str = "ingestion"
    status: str = "active"
    claim_key: str = ""
    env_scope: str = ""
    link_run_id: str = ""
    metadata: dict = field(default_factory=dict)
    extra_props: dict = field(default_factory=dict)
    created_at: str = field(default_factory=_utcnow)

    def is_lite(self) -> bool:
        """Extracted structural bulk stores only what varies (design §5.4)."""
        return (self.origin == "extracted" and self.created_by == "ingestion"
                and self.confidence >= 1.0 and not self.evidence and not self.claim_key)

    def to_neo4j_props(self) -> dict:
        props = {"created_at": self.created_at}
        if self.label:
            props["label"] = self.label
        if self.weight != 1:
            props["weight"] = self.weight
        if self.metadata:
            props["metadata"] = json.dumps(self.metadata)
        if self.is_lite():
            return props
        props.update({
            "confidence": float(self.confidence),
            "origin": self.origin,
            "created_by": self.created_by,
            "status": self.status,
            "envelope_version": ENVELOPE_VERSION,
        })
        if self.detected_by:
            props["detected_by"] = self.detected_by
        if self.match_type:
            props["match_type"] = self.match_type
        if self.evidence:
            props["evidence"] = self.evidence[:5]
        if self.source_repo_id:
            props["source_repo_id"] = self.source_repo_id
        if self.target_repo_id:
            props["target_repo_id"] = self.target_repo_id
            props["cross_repo"] = bool(self.cross_repo)
        if self.claim_key:
            props["claim_key"] = self.claim_key
        if self.env_scope:
            props["env_scope"] = self.env_scope
        if self.link_run_id:
            props["link_run_id"] = self.link_run_id
        for key, value in self.extra_props.items():
            if isinstance(value, (str, int, float, bool)) or (
                    isinstance(value, list)
                    and all(isinstance(v, (str, int, float, bool)) for v in value)):
                props[key] = value
        return props


@dataclass
class IngestionJob:
    """Ingestion/linker job state."""
    id: str
    repo_id: str
    status: str = "queued"  # queued, running, completed, failed
    progress: int = 0
    message: str = ""
    error: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)

    def to_neo4j_props(self) -> dict:
        return {
            "id": self.id,
            "repo_id": self.repo_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
