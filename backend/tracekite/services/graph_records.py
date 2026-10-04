"""Neo4j rows to API models: the one place a stored node or edge is read back.

Shared by every per-repository graph read — views, impact, search, details —
because the mapping is a decision (which properties are core, which fold into
metadata, what a Lite-tier edge defaults to), and two copies of a decision drift.
"""

from tracekite.services.graph_properties import json_safe, parse_json
from tracekite.models.api_models import GraphLink, GraphNode
from tracekite.models.graph_models import LITE_DEFAULTS

NODE_SIZES = {
    "Repo": 20, "Folder": 12, "File": 8, "Class": 10, "Interface": 9,
    "Method": 6, "Function": 6, "ApiEndpoint": 11, "Dependency": 7,
    "Config": 6, "DockerResource": 9, "KubernetesResource": 9,
}

CORE_NODE_PROPS = {"id", "type", "name", "label", "path", "language", "repo_id",
                   "metadata", "created_at", "updated_at"}

EDGE_RETURN = (
    "a.id AS source, b.id AS target, type(r) AS type, r.label AS label, "
    "r.weight AS weight, r.confidence AS confidence, r.origin AS origin, "
    "r.detected_by AS detected_by"
)


def node_from_props(props: dict, size_bonus: int = 0) -> GraphNode:
    metadata = parse_json(props.get("metadata"))
    for key, value in props.items():
        if key not in CORE_NODE_PROPS and value is not None:
            metadata.setdefault(key, json_safe(value))
    node_type = props.get("type") or ""
    name = props.get("name") or ""
    return GraphNode(
        id=props.get("id") or "",
        type=node_type,
        label=props.get("label") or name,
        name=name,
        path=props.get("path"),
        language=props.get("language") or "",
        size=NODE_SIZES.get(node_type, 7) + size_bonus,
        group=node_type,
        metadata=metadata,
    )


def link_from_record(record) -> GraphLink:
    confidence = record["confidence"]
    return GraphLink(
        source=record["source"],
        target=record["target"],
        type=record["type"],
        label=record["label"] or record["type"].lower(),
        value=int(record["weight"] or 1),
        confidence=float(confidence) if confidence is not None
        else LITE_DEFAULTS["confidence"],
        origin=record["origin"] or LITE_DEFAULTS["origin"],
        detected_by=record["detected_by"],
    )
