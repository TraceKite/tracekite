---
name: evigraph
description: Cross-repository dependency tracing with file:line evidence.
---

# Evigraph

Use the Evigraph MCP tools for cross-repository caller, dependency, and impact
questions:

- `services()` lists repository-backed services in the loaded graph.
- `consumers_of(node_id)` returns active incoming edges with evidence spans.
- `trace(from_id, to_id)` returns active paths between exact node IDs.
- `deprecations()` reports deprecated contracts and their active consumers.

Treat an empty or declined result as evidence that Evigraph could not establish
the relationship. Never infer an edge that the tools did not return. Open the
cited source location when method-level implementation detail is required.
