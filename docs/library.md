# Embed TraceKite in Python

[Docs](README.md) · Reference: [MCP/query methods](mcp-tools.md) · [Reading answers](answers.md)

Use the public `TraceKite` facade for graph questions. It scans or loads inputs
once on the first query, links them in memory, and reuses that snapshot.
It needs neither the app server nor Neo4j.

## First query

Requires Python 3.13+. From the repository checkout, using the included demo:

```bash
pip install tracekite-core
export GRAPH_HMAC_KEY="$(openssl rand -hex 32)"
```

Generate the private key once and retain it for related scans. Run this Python
example from the checkout root:

```python
import os
from tracekite.facade import TraceKite

tk = TraceKite(
    ["corpus/orders-service", "corpus/billing-service"],
    graph_hmac_key=os.environ["GRAPH_HMAC_KEY"],
)

services = tk.services()
print(services.result["services"])

answer = tk.consumers_of("global:Service:billing-service")
print(answer.status.value)
for consumer in answer.result.get("consumers", []):
    print(consumer["consumer"], consumer["evidence"])
```

Expected: `present` and the orders service as a consumer, with source citations.
Use IDs returned by `services()` or `search()` for your own inputs.

## All query methods

| Method | Result field |
|---|---|
| `tk.services()` | `services` and `commits` |
| `tk.search("BillingClient", limit=20)` | `matches` |
| `tk.node(node_id)` | `node` |
| `tk.consumers_of(node_id)` | `consumers` |
| `tk.trace(from_id, to_id, max_hops=6)` | `paths` |
| `tk.neighbors(node_id, direction="both", depth=1, limit=100)` | `neighbors`, `edges` |
| `tk.subgraph(node_id, depth=2, node_limit=100, edge_limit=250)` | `nodes`, `edges` |
| `tk.impact(node_id, depth=6, limit=100, min_confidence=0.0)` | `impacted` |
| `tk.deprecations()` | `contracts` |

Graph traversal methods also accept the edge filters listed in the
[query reference](mcp-tools.md). They traverse linker relationships, not every
local `CONTAINS`, `DECLARES`, or `CALLS` edge from a scan.

## Read the whole envelope

```python
payload = answer.model_dump(mode="json")
print(payload["status"], payload["reason"])
print(payload["scope"]["truncation"])
print(payload["completeness"])
print(payload["snapshot"]["repos"])
```

Always inspect truncation as well as completeness. A complete scan can still
produce a capped query. `freshness` is currently `unknown`; a long-running
instance does not watch source changes. Create a new instance to reload.

**0.2.0 compatibility note:** Python `services()` and `deprecations()` return
status `present` even when their result collections are empty. MCP classifies
those empty collections as `known_empty`. Check the collection itself in a
host supporting this release. Both surfaces also report service completeness
conservatively when a supplied repository produces no service identity.

## Use artifacts

Pass `.tracekite` paths instead of source directories, or mix the two:

```python
# Replace these with the filenames printed by `tracekite artifact`.
orders_artifact = "/path/to/orders-SNAPSHOT.tracekite"
billing_artifact = "/path/to/billing-SNAPSHOT.tracekite"
tk = TraceKite([orders_artifact, billing_artifact],
               graph_hmac_key=os.environ["GRAPH_HMAC_KEY"])
```

Create one artifact per repository. Directory IDs come from basenames; artifact
IDs come from their metadata. Duplicate IDs are rejected. Artifact loading reads
claims for linking and resolves source-node metadata lazily from SQLite.

## Lower-level scan and link

Use this when your host needs scan nodes, all local edges, or its own persistence:

```python
import os
from tracekite import engine_config
from tracekite.db.memory_store import InMemoryLinkerStore
from tracekite.services.linker.engine import link
from tracekite.services.scan import scan

engine_config.configure(graph_hmac_key=os.environ["GRAPH_HMAC_KEY"])
sinks = [
    scan("corpus/orders-service", "orders-service"),
    scan("corpus/billing-service", "billing-service"),
]
result = link(InMemoryLinkerStore(sinks).load_claims(),
              run_id="demo", now="2026-01-01T00:00:00+00:00")
print(len(result.edges), result.counters)
```

`sinks` hold local source nodes/edges. `result` holds the linker-derived edges,
services, shared contract nodes, and counters. Your host decides whether to save
them. Engine configuration is process-wide; isolate hosts that need different
configurations concurrently.

## Storage and extension points

| Need | Implementation |
|---|---|
| No persistence | Keep scan sinks and `LinkResult` in memory |
| Query a portable local graph | [`SQLiteGraphStore`](../backend/tracekite/db/sqlite_store.py) |
| Use Neo4j | Install `tracekite-core[neo4j]`; use [`Neo4jGraphStore`](../backend/tracekite/db/neo4j_graph_store.py) |
| Store contract | [`GraphStore`](../backend/tracekite/db/graph_store.py): upserts, typed queries, deletion by run |
| Drive a full link run | [`LinkerStore`](../backend/tracekite/services/linker/ports.py): the separate, narrower link-run contract |
| Merge artifact records | [`compact`](../backend/tracekite/db/artifact.py); use a fresh output database and inspect `skipped`; compaction is not a link run |
| Parallel scans and artifact reuse | [`parallel_map`](../backend/tracekite/services/parallel_map.py) |
| Custom resolver or result hook | [`registry`](../backend/tracekite/services/linker/registry.py), [`hooks`](../backend/tracekite/services/linker/hooks.py) |

These lower-level modules expose implementation contracts; prefer the facade
for integrations that only need answers. Read [architecture](design/architecture.md)
and [contributing](../CONTRIBUTING.md) before extending extraction or linking.
