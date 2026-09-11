"""Source-file ingestion pass: symbols with stable identity, endpoints, coverage.

Symbol ids never embed line numbers (Invariant 3): identity comes from a
signature hash plus a declaration-order occurrence index, so edits above a
symbol do not churn its id.
"""

import logging
from dataclasses import dataclass, field

from evigraph.models.graph_models import GraphEdge, GraphNode
from evigraph.services.graph_factories import (
    create_declares_edge, create_endpoint_node, create_exposes_api_edge,
)
from evigraph.utils.hashing import build_symbol_uid, generate_node_id, symbol_extra
from evigraph.services.framework_routes import framework_routes

logger = logging.getLogger(__name__)

ENTITY_TYPE_MAP = {"class": "Class", "interface": "Interface",
                   "method": "Method", "function": "Function"}

TIER_RANK = {"none": 0, "lite": 1, "full": 2}


@dataclass
class IngestSink:
    """Accumulates nodes/edges plus parse coverage during one ingestion run."""
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    node_ids: set[str] = field(default_factory=set)
    parse_context: dict[str, dict] = field(default_factory=dict)
    coverage: dict[str, dict] = field(default_factory=dict)
    claims: dict[str, int] = field(default_factory=dict)
    # 0 disables the ceiling; a host that wants everything can ask for it.
    max_claims: int = 0
    capped: dict[str, int] = field(default_factory=dict)
    # Submodule paths declared but not present on disk.
    unfetched_submodules: list[str] = field(default_factory=list)
    # What the scan looked for and did not find.
    absence: dict = field(default_factory=dict)

    def count_claim(self, kind: str) -> None:
        self.claims[kind] = self.claims.get(kind, 0) + 1

    def claims_total(self) -> int:
        return sum(v for k, v in self.claims.items() if not k.startswith("_"))

    def claim_budget_exhausted(self) -> bool:
        """Whether the repo has hit its claim ceiling.

        Counted rather than enforced silently: `capped` is what tells a
        reviewer the graph is deliberately incomplete, and without it a
        truncated scan looks exactly like a small repository.
        """
        if self.max_claims and self.claims_total() >= self.max_claims:
            self.capped["claims"] = self.capped.get("claims", 0) + 1
            return True
        return False

    def add_node(self, node: GraphNode) -> bool:
        if node.id in self.node_ids:
            return False
        self.node_ids.add(node.id)
        self.nodes.append(node)
        return True

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)

    def lang(self, language: str) -> dict:
        return self.coverage.setdefault(language or "Unknown", {
            "files_seen": 0, "files_parsed": 0, "parse_errors": 0,
            "files_skipped_large": 0, "entities": 0, "endpoints": 0,
            "imports_unemitted": 0, "tier": "none",
        })

    def upgrade_tier(self, language: str, tier: str) -> None:
        counters = self.lang(language)
        if TIER_RANK.get(tier, 0) > TIER_RANK.get(counters["tier"], 0):
            counters["tier"] = tier


def process_source_file(repo_id: str, file_info, source, file_node_id: str,
                        sink: IngestSink, tier: str, content: str = "") -> None:
    """Convert one file's ParseResult into nodes/edges with stable symbol ids."""
    counters = sink.lang(file_info.language)
    counters["files_parsed"] += 1
    sink.upgrade_tier(file_info.language, tier)
    counters["imports_unemitted"] += len(source.imports)

    occurrence: dict[tuple[str, int], int] = {}
    file_entities: list[dict] = []

    for entity in sorted(source.entities, key=lambda e: (e.start_line, e.name)):
        node_type = ENTITY_TYPE_MAP.get(entity.type)
        if node_type is None:
            continue
        entity_meta = entity.metadata or {}
        arity = len(entity_meta.get("parameters") or [])
        occ_key = (entity.name, arity)
        occ_index = occurrence.get(occ_key, 0)
        occurrence[occ_key] = occ_index + 1

        entity_id = generate_node_id(
            repo_id, node_type, file_info.path, entity.name,
            extra=symbol_extra(entity.name, arity, occ_index),
        )
        parent_class = entity_meta.get("parent_class")
        qualified_name = f"{parent_class}.{entity.name}" if parent_class else entity.name

        metadata = {k: v for k, v in entity_meta.items()
                    if k not in ("parameters",) and v not in (None, "", [])}
        if entity.annotations:
            metadata["annotations"] = entity.annotations
        if entity.modifiers:
            metadata["modifiers"] = entity.modifiers

        node = GraphNode(
            id=entity_id,
            repo_id=repo_id,
            type=node_type,
            name=entity.name,
            label=entity.name,
            path=file_info.path,
            language=file_info.language,
            start_line=entity.start_line,
            end_line=entity.end_line,
            signature=entity.signature or None,
            symbol_uid=build_symbol_uid(
                repo_id, (file_info.language or "unknown").lower(),
                file_info.path, qualified_name, arity,
            ),
            extra_props={"arity": arity},
            metadata=metadata,
        )
        if not sink.add_node(node):
            continue
        counters["entities"] += 1
        sink.add_edge(create_declares_edge(repo_id, file_node_id, entity_id, entity.type))

        record = {
            "id": entity_id,
            "repo_id": repo_id,
            "file_path": file_info.path,
            "name": entity.name,
            "qualified_name": qualified_name,
            "parent_class": parent_class,
            "type": entity.type,
            "start_line": entity.start_line,
            "end_line": entity.end_line,
        }
        file_entities.append(record)

    endpoint_records = _process_endpoints(repo_id, file_info, source, file_node_id,
                                          sink, file_entities, counters)
    endpoint_records = _merge_framework_routes(
        repo_id, file_info, content, file_node_id, sink, file_entities,
        counters, endpoint_records)

    from evigraph.services.ingest_claims import emit_source_claims
    emit_source_claims(repo_id, file_info, content, endpoint_records,
                       file_node_id, sink)

    sink.parse_context[file_info.path] = {
        "file_node_id": file_node_id,
        "language": file_info.language,
        "entities": file_entities,
        "method_calls": source.method_calls or [],
    }


def _merge_framework_routes(repo_id: str, file_info, content: str,
                            file_node_id: str, sink: IngestSink,
                            file_entities: list[dict], counters: dict,
                            records: list[dict]) -> list[dict]:
    """Merge extractor routes with parser endpoints, preferring resolved paths.

    The legacy JS parser emits `router.get('/pets')` as an unprefixed Express
    row; when the extractor resolved the same route through its mount/controller
    prefix (`/v1/pets`), the unprefixed row is the same statement half-parsed —
    keeping both would double-count the endpoint and emit a phantom contract.
    """
    routes, declined = framework_routes(file_info, content)
    if declined:
        counters["endpoints_computed_path"] = (
            counters.get("endpoints_computed_path", 0) + declined)
    if not routes:
        return records

    from evigraph.services.graph_factories import create_endpoint_node

    existing = {(r["http_method"], r["path_template"]) for r in records}
    for route in routes:
        superseded = [r for r in records
                      if r["http_method"] in (route.method, "ANY")
                      and r["path_template"] != route.path
                      and r["path_template"] != "/"
                      and route.path.endswith(r["path_template"])]
        for old in superseded:
            _remove_endpoint(sink, old, counters)
            records.remove(old)
            existing.discard((old["http_method"], old["path_template"]))

        if (route.method, route.path) in existing:
            continue
        node = create_endpoint_node(
            repo_id, file_info.path, file_info.language, route.method,
            route.path, route.framework, route.handler_name, None, route.line,
        )
        if not sink.add_node(node):
            continue
        counters["endpoints"] += 1
        existing.add((route.method, route.path))
        records.append({
            "node_id": node.id,
            "http_method": node.extra_props.get("http_method", route.method),
            "path_template": node.extra_props.get("path_template", route.path),
            "framework": route.framework,
            "line": route.line,
        })
        handler_id = _resolve_handler(file_entities, route)
        sink.add_edge(create_exposes_api_edge(
            repo_id, handler_id or file_node_id, node.id,
            evidence=[f"{file_info.path}:{route.line or 1}"],
        ))
    return records


def _remove_endpoint(sink: IngestSink, record: dict, counters: dict) -> None:
    node_id = record["node_id"]
    sink.nodes = [n for n in sink.nodes if n.id != node_id]
    sink.node_ids.discard(node_id)
    sink.edges = [e for e in sink.edges if e.target_id != node_id]
    counters["endpoints"] = max(0, counters["endpoints"] - 1)


def _process_endpoints(repo_id: str, file_info, source, file_node_id: str,
                       sink: IngestSink, file_entities: list[dict],
                       counters: dict) -> list[dict]:
    # Same rule the claims layer already enforces, one level up: a test or
    # vendored file's endpoints are fixtures, not this repo's API surface.
    # The bare-call heuristics make this concrete — `jc.delete("/path")`
    # against a mocked client in a test became a DELETE provider — and no
    # receiver-name blocklist can enumerate every variable name. Provenance
    # is the generic discriminator, and it is already computed centrally.
    from evigraph.services.file_classifier import classify
    provenance = classify(file_info.path).reason
    if provenance in ("test", "vendored"):
        n = len(source.api_endpoints or [])
        if n:
            counters["endpoints_nonproduction_skipped"] = (
                counters.get("endpoints_nonproduction_skipped", 0) + n)
        return []

    records = []
    for endpoint in source.api_endpoints:
        # An ellipsis is prose, never a path segment: every framework's
        # dynamic segment has its own spelling ({id}, [id], :id, [...slug])
        # and each extractor canonicalizes it. A literal "..." reaching this
        # point is an extractor emitting a placeholder as data — the defect
        # that put 23 `/api/...` endpoints in the graph — and it is refused
        # here as well so a future extractor cannot reintroduce it.
        if "..." in (endpoint.path or ""):
            counters["endpoints_placeholder_path"] = (
                counters.get("endpoints_placeholder_path", 0) + 1)
            continue
        node = create_endpoint_node(
            repo_id, file_info.path, file_info.language, endpoint.method,
            endpoint.path, endpoint.framework, endpoint.handler_name,
            endpoint.controller_name, endpoint.line,
        )
        if sink.add_node(node):
            counters["endpoints"] += 1
            records.append({
                "node_id": node.id,
                "http_method": node.extra_props.get("http_method", "GET"),
                "path_template": node.extra_props.get("path_template", "/"),
                "framework": endpoint.framework,
                "line": endpoint.line,
            })

        handler_id = _resolve_handler(file_entities, endpoint)
        sink.add_edge(create_exposes_api_edge(
            repo_id, handler_id or file_node_id, node.id,
            evidence=[f"{file_info.path}:{endpoint.line or 1}"],
        ))
    return records


def _resolve_handler(file_entities: list[dict], endpoint) -> str | None:
    candidates = [
        record for record in file_entities
        if record["name"] == endpoint.handler_name
        and record["type"] in ("method", "function")
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda r: abs(r["start_line"] - (endpoint.line or 0)))
    return best["id"]
