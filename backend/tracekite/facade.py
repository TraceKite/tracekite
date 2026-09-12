"""Stable framework integration facade.

A host embeds TraceKite through this module — no FastAPI, no Neo4j, no
network.  The facade accepts source directories or ``.tracekite`` artifacts,
scans and links them once on first query, and returns every answer wrapped
in the versioned ``AnswerEnvelope`` contract.

Usage::

    import os
    from tracekite.facade import TraceKite

    tk = TraceKite(
        ["/path/to/repo-a", "/path/to/repo-b"],
        graph_hmac_key=os.environ["GRAPH_HMAC_KEY"],
    )
    answer = tk.consumers_of("global:Service:my-service")
    print(answer.status, answer.completeness.complete)

The four methods (``services``, ``consumers_of``, ``trace``,
``deprecations``) mirror the existing MCP tools.  Each returns an
``AnswerEnvelope`` carrying snapshot identity, query scope, completeness
and freshness alongside the tool-specific result.
"""

from __future__ import annotations

import os
from typing import Any

from tracekite.answer import (
    AnswerEnvelope,
    AnswerStatus,
    CONFIG_VERSION,
    CompletenessAssessment,
    ENGINE_VERSION,
    FreshnessState,
    QueryScope,
    SnapshotIdentity,
    TruncationInfo,
)
from tracekite.completeness import evaluate_completeness
from tracekite.scan_meta import (
    ScanMeta,
    config_digest,
    repo_scan_meta_from_sink,
)
from tracekite.source_meta import collect_input_meta
from tracekite.status_classify import classify_consumers, classify_trace

def collect_claims(path: str, claims: list, commits: dict,
                   sinks: dict | None = None) -> None:
    """Scan or load one input, appending claims and revision metadata.

    Extracted from ``mcp_server`` so the facade is self-contained and the
    MCP server can delegate here without a circular import.

    If ``sinks`` is provided, directory scans retain their ``IngestSink``
    keyed by ``repo_id`` so the caller can extract scan-level metadata
    (caps, absence, parse coverage) without a second scan.
    """
    from tracekite.db.artifact import read_meta
    from tracekite.db.artifact_reader import read_claims
    from tracekite.db.memory_store import claims_from_scan
    from tracekite.services.scan import scan

    if os.path.isfile(path) and path.endswith(".tracekite"):
        meta = read_meta(path)
        repo_ids = ([meta["repo_id"]] if meta.get("repo_id") else
                    list(meta.get("repos") or []))
        if not repo_ids:
            raise ValueError(f"artifact has no repository identity: {path}")
        _register_repos(repo_ids, commits, meta.get("head_sha", ""))
        claims.extend(read_claims(path))
        return
    if os.path.isdir(path):
        repo_id = os.path.basename(os.path.abspath(path))
        _register_repos([repo_id], commits)
        sink = scan(path, repo_id=repo_id)
        claims.extend(claims_from_scan(sink))
        if sinks is not None:
            sinks[repo_id] = sink
        return
    if os.path.exists(path):
        raise ValueError(f"unsupported input (expected .tracekite): {path}")
    raise FileNotFoundError(path)


def _register_repos(repo_ids: list[str], commits: dict,
                    head_sha: str = "") -> None:
    duplicates = sorted(set(repo_ids) & set(commits))
    if duplicates:
        raise ValueError(f"duplicate repository inputs: {duplicates}")
    commits.update((repo_id, head_sha) for repo_id in repo_ids)


def load_graph(paths: list[str], *,
               graph_hmac_key: str = "") -> tuple[Any, SnapshotIdentity, ScanMeta]:
    """Scan/link all inputs once and build snapshot identity and scan metadata.

    Returns ``(GraphTools, SnapshotIdentity, ScanMeta)``.
    """
    from tracekite import engine_config
    from tracekite.mcp_server import GraphTools
    from tracekite.services.linker.engine import link

    if graph_hmac_key:
        engine_config.configure(graph_hmac_key=graph_hmac_key)

    claims: list = []
    revisions, scan_meta = collect_input_meta(paths)
    commits: dict = {}
    sinks: dict[str, Any] = {}

    for path in paths:
        collect_claims(path, claims, commits, sinks=sinks)

    for repo_id, sink in sinks.items():
        cfg = engine_config.get_config()
        scan_meta.add(repo_scan_meta_from_sink(
            sink, repo_id, budgets={
                "files": cfg.max_files_per_repo,
                "claims": cfg.max_claims_per_repo,
            }))

    result = link(claims, run_id="linkrun_facade",
                  now="2026-01-01T00:00:00+00:00")
    tools = GraphTools(result, commits=commits)

    cfg = engine_config.get_config()
    snapshot = SnapshotIdentity(
        repos=revisions,
        engine_version=ENGINE_VERSION,
        config_version=CONFIG_VERSION,
        config_digest=config_digest(cfg),
    )
    return tools, snapshot, scan_meta


def _scope(query_kind: str, **params) -> QueryScope:
    return QueryScope(query_kind=query_kind, parameters=params)


def _envelope(
    status: AnswerStatus,
    result: dict,
    snapshot: SnapshotIdentity,
    scope: QueryScope,
    completeness: CompletenessAssessment | None = None,
    candidates: list[str] | None = None,
    reason: str = "",
) -> AnswerEnvelope:
    return AnswerEnvelope(
        status=status,
        snapshot=snapshot,
        scope=scope,
        completeness=completeness or CompletenessAssessment(),
        freshness=FreshnessState.UNKNOWN,
        result=result,
        candidates=candidates or [],
        reason=reason,
    )


class TraceKite:
    """Public facade for framework integrations.

    No server, no database.  Scan and link happen once, on the first
    query; subsequent calls answer from the in-memory graph.

    ``graph_hmac_key`` configures the HMAC salt used to redact config
    values in claims.  Hosts must pass it here or configure
    ``engine_config`` before the first query; redaction fails closed when no
    key is available.
    """

    def __init__(self, paths: list[str], *, graph_hmac_key: str = ""):
        self._paths = paths
        self._graph_hmac_key = graph_hmac_key
        self._tools: Any = None
        self._snapshot: SnapshotIdentity | None = None
        self._scan_meta: ScanMeta | None = None

    def _ensure_loaded(self) -> None:
        if self._tools is None:
            self._tools, self._snapshot, self._scan_meta = load_graph(
                self._paths, graph_hmac_key=self._graph_hmac_key)

    def services(self) -> AnswerEnvelope:
        self._ensure_loaded()
        raw = self._tools.services()
        # Compare repository IDs: each service lists the repos that back it;
        # completeness checks those repos against the repos we declared.
        analyzed_repos = sorted(set(
            rid for s in raw.get("services", [])
            for rid in s.get("repos", [])
        ))
        comp = self._completeness(analyzed_repos)
        return _envelope(
            AnswerStatus.PRESENT, raw, self._snapshot,
            _scope("services").model_copy(update={
                "expected_repos": self._repo_ids(),
                "analyzed_repos": analyzed_repos,
                "truncation": self._truncation(),
            }),
            comp,
        )

    def consumers_of(self, node_id: str) -> AnswerEnvelope:
        self._ensure_loaded()
        raw = self._tools.consumers_of(node_id)
        status, candidates, reason = classify_consumers(raw)
        comp = self._completeness(self._repo_ids())
        scope = _scope("consumers_of", node_id=node_id)
        scope = scope.model_copy(update={
            "expected_repos": self._repo_ids(),
            "analyzed_repos": self._repo_ids(),
            "truncation": self._truncation(),
        })
        return _envelope(status, raw, self._snapshot, scope, comp,
                         candidates=candidates, reason=reason)

    def trace(self, from_id: str, to_id: str,
              max_hops: int = 6) -> AnswerEnvelope:
        self._ensure_loaded()
        raw = self._tools.trace(from_id, to_id, max_hops=max_hops)
        known = self._tools._known_node_ids() if self._tools else set()
        status, candidates, reason = classify_trace(raw, known)
        comp = self._completeness(self._repo_ids())
        scope = _scope("trace", from_id=from_id, to_id=to_id, max_hops=max_hops)
        scope = scope.model_copy(update={
            "expected_repos": self._repo_ids(),
            "analyzed_repos": self._repo_ids(),
            "truncation": self._truncation(),
        })
        return _envelope(status, raw, self._snapshot, scope, comp,
                         candidates=candidates, reason=reason)

    def deprecations(self) -> AnswerEnvelope:
        self._ensure_loaded()
        raw = self._tools.deprecations()
        comp = self._completeness(self._repo_ids())
        scope = _scope("deprecations")
        scope = scope.model_copy(update={
            "expected_repos": self._repo_ids(),
            "analyzed_repos": self._repo_ids(),
            "truncation": self._truncation(),
        })
        return _envelope(AnswerStatus.PRESENT, raw, self._snapshot,
                         scope, comp)

    def _completeness(self, analyzed_repos: list[str]) -> CompletenessAssessment:
        scan_meta = getattr(self, "_scan_meta", None)
        scan_completed = True
        parse_failures = 0
        result_truncated = False
        if scan_meta is not None:
            scan_completed = all(
                m.scan_completed for m in scan_meta.repos.values())
            parse_failures = scan_meta.total_parse_failures
            result_truncated = scan_meta.any_truncated
        return evaluate_completeness(
            expected_repos=self._repo_ids(),
            analyzed_repos=analyzed_repos,
            scan_completed=scan_completed,
            parse_failures=parse_failures,
            result_truncated=result_truncated,
            coverage_reasons=(
                scan_meta.absence_reasons() if scan_meta is not None else []
            ),
        )

    def _truncation(self) -> TruncationInfo:
        scan_meta = getattr(self, "_scan_meta", None)
        if scan_meta is not None:
            return scan_meta.truncation_info()
        return TruncationInfo()

    def _repo_ids(self) -> list[str]:
        if self._snapshot is None:
            return []
        return [r.repo_id for r in self._snapshot.repos]
