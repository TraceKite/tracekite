"""One file's routes from two readers, merged into one set of endpoints.

The generic parser matches a pattern per language over method calls; the
framework extractor knows which framework it is reading and resolves mounts,
groups and controller prefixes. Where both report a route, the framework
extractor is the more specific reader and wins:

- the same method and template: its row replaces the generic one, so a
  fastify route is not labelled express and an echo route not gin.
- the generic row is its unprefixed half (`/users/{}` of `/admin/users/{}`):
  the generic row is dropped. Keeping both emitted a phantom contract.

Templates are compared canonically on both sides. The extractor's raw
`/admin/users/{id}` against the generic row's canonical `/users/{}` never
matched, so every parameterised route kept its phantom.
"""

from tracekite.services.framework_routes import framework_routes
from tracekite.services.graph_factories import (
    create_endpoint_node, create_exposes_api_edge,
)
from tracekite.utils.canonical import (
    canonicalize_path_template, normalize_http_method,
)


def resolve_handler(file_entities: list[dict], endpoint) -> str | None:
    candidates = [
        record for record in file_entities
        if record["name"] == endpoint.handler_name
        and record["type"] in ("method", "function")
    ]
    if not candidates:
        return None
    best = min(candidates, key=lambda r: abs(r["start_line"] - (endpoint.line or 0)))
    return best["id"]


def _superseded_by(record: dict, method: str, template: str) -> bool:
    """Only a generic row gives way: two routes the framework extractor read
    are two routes, even when one path ends with the other."""
    if record.get("from_framework") or record["http_method"] not in (method, "ANY"):
        return False
    old = record["path_template"]
    return old == template or (old != "/" and template.endswith(old))


def _remove_endpoint(sink, record: dict, counters: dict) -> None:
    node_id = record["node_id"]
    sink.nodes = [n for n in sink.nodes if n.id != node_id]
    sink.node_ids.discard(node_id)
    sink.edges = [e for e in sink.edges if e.target_id != node_id]
    counters["endpoints"] = max(0, counters["endpoints"] - 1)


def merge_framework_routes(repo_id: str, file_info, content: str,
                           file_node_id: str, sink, file_entities: list[dict],
                           counters: dict, records: list[dict]) -> list[dict]:
    routes, declined = framework_routes(file_info, content)
    if declined:
        counters["endpoints_computed_path"] = (
            counters.get("endpoints_computed_path", 0) + declined)
    for route in routes:
        method = normalize_http_method(route.method)
        template = canonicalize_path_template(route.path)
        for old in [r for r in records if _superseded_by(r, method, template)]:
            _remove_endpoint(sink, old, counters)
            records.remove(old)
        if any((r["http_method"], r["path_template"]) == (method, template)
               for r in records):
            continue
        node = create_endpoint_node(
            repo_id, file_info.path, file_info.language, route.method,
            route.path, route.framework, route.handler_name, None, route.line,
        )
        if not sink.add_node(node):
            continue
        counters["endpoints"] += 1
        records.append({
            "node_id": node.id,
            "http_method": node.extra_props.get("http_method", method),
            "path_template": node.extra_props.get("path_template", template),
            "framework": route.framework,
            "line": route.line,
            "from_framework": True,
        })
        handler_id = resolve_handler(file_entities, route)
        sink.add_edge(create_exposes_api_edge(
            repo_id, handler_id or file_node_id, node.id,
            evidence=[f"{file_info.path}:{route.line or 1}"],
        ))
    return records
