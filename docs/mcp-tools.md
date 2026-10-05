# MCP and Python graph queries

[Docs](README.md) · [MCP setup](plugins-and-mcp-guide.md) · [Python](library.md)

Start with `services` or `search`, copy an exact ID, then inspect or traverse it.
These tools operate on a graph loaded from source directories or artifacts,
not on the Docker app's database.

## All nine tools

Arguments in backticks show their defaults; `node_id`, `query`, `from_id`, and
`to_id` are required where listed. The Python facade mirrors these signatures.

| Tool | Inputs | Output |
|---|---|---|
| `services` | None | Repository-backed service IDs/names and commit metadata |
| `node` | `node_id` | Identity, repository, path, and available properties |
| `search` | `query`, `limit=20` (1–100) | Ranked `matches` and `truncated` |
| `consumers_of` | `node_id` | Direct incoming dependency relationships and evidence |
| `trace` | `from_id`, `to_id`, `max_hops=6` (1–8) | Up to three shortest active directed paths |
| `neighbors` | `node_id`, `direction="both"`, `depth=1`, `edge_types=null`, `limit=100` | Adjacent identities, distance, traversed edges, total, truncation |
| `impact` | `node_id`, `depth=6`, `limit=100`, `min_confidence=0.0`, `edge_types=null` | Dependents with distance, evidence paths, and path confidence |
| `subgraph` | `node_id`, `depth=2`, `direction="both"`, `edge_types=null`, `node_limit=100`, `edge_limit=250` | Focus + neighbors and edges between returned nodes |
| `deprecations` | None | Deprecated contracts and active indexed consumers |

For `neighbors`, `impact`, and `subgraph`, depth is 1–8. Neighbor/impact limits
are 1–500; subgraph nodes are 2–500 and edges 1–1000. Direction is `in`, `out`,
or `both`; minimum confidence is 0–1. `edge_types` is a list of registered type
names; omitting it or passing `[]` means no type filter.

`impact.min_confidence` filters individual edges. Returned path confidence
also compounds the edges, so a multi-hop path's product may be below that value.

## A useful investigation

With the [demo repositories](cli.md#install-and-run-the-demo) loaded, ask your
agent to perform these tool calls:

```text
services()
node(node_id="global:Service:billing-service")
consumers_of(node_id="global:Service:billing-service")
trace(from_id="global:Service:orders-service",
      to_id="global:Service:billing-service", max_hops=3)
```

Then inspect a bounded neighborhood:

```json
{
  "node_id": "global:Service:billing-service",
  "direction": "both",
  "depth": 2,
  "edge_types": ["CALLS_SERVICE"],
  "limit": 25
}
```

Pass that JSON as the arguments to `neighbors`. Expect the orders service and
its cited relationship. Do not guess opaque source-node IDs: search by name or
path, then use `node` to confirm the match.

## Semantics that matter

- Friendly service names work only when unambiguous. Retry with a returned
  candidate ID when status is `ambiguous`.
- `consumers_of` selects dependency edge types; it is not every incoming edge.
  Some contracts include implementing/provider nodes as dependents.
- `neighbors` and `subgraph` traverse stored arrow direction. They do not
  reinterpret a topic's consumer arrow as message flow.
- `impact` follows dependency edges backwards. `trace` follows active edges
  forwards. Neither is the same query as the app's local Repo Impact mode.
- Traversals use **linker edges**. Identity lookup includes source nodes, but
  the MCP graph does not load every local containment or symbol-call edge.
- A bounded response can omit results. Read `truncated`, totals, and
  `scope.truncation`; do not infer absence from an output cap.

See [graph model](graph-model.md) for types/direction and
[reading answers](answers.md) for statuses and evidence fields.

## Raw transport check

From the TraceKite checkout, this lists tools without scanning repositories:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | tracekite mcp corpus/orders-service corpus/billing-service
```

The stdio transport uses one JSON-RPC message per line. It advertises MCP
protocol `2024-11-05`. Normal clients handle initialization and tool calls.
`tools/call` responses contain a JSON answer in `result.content[0].text`.
Unknown tools/invalid arguments return protocol errors; failed graph loading
returns an error, not an empty graph answer.
