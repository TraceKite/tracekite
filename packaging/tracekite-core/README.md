# tracekite-core

Find supported connections across source repositories, with file-and-line
evidence. TraceKite reads code and configuration to connect services, endpoints,
packages, topics, and datasets. It does not execute your applications.

## Install

Requires Python 3.13 or later:

```bash
pip install tracekite-core
tracekite --help
```

The library, CLI, and MCP server need no FastAPI server or Neo4j database.

## Try two local repositories

Replace these paths with your checkouts:

```bash
tracekite scan /path/to/orders --repo-id orders
tracekite link /path/to/orders /path/to/billing
```

`scan` reports counts/coverage; `link` prints edges, confidence, evidence, and
resolver counters. For a copyable example with known results, use the
[small demo](https://github.com/TraceKite/tracekite/blob/main/docs/cli.md#install-and-run-the-demo).
Set a private, stable `GRAPH_HMAC_KEY` before scanning sensitive configuration.

## Embed or connect an agent

```python
import os
from tracekite.facade import TraceKite

tk = TraceKite(["/path/to/orders", "/path/to/billing"],
               graph_hmac_key=os.environ["GRAPH_HMAC_KEY"])
print(tk.services().model_dump(mode="json"))
```

The facade and MCP provide `services`, `node`, `search`, `consumers_of`, `trace`,
`neighbors`, `impact`, `subgraph`, and `deprecations`. Start an MCP stdio server
with `tracekite mcp /path/to/orders /path/to/billing`; your client normally runs
that command for you. Inputs load once and require a restart to pick up changes.

They query their own in-memory graph, not the Docker application's database.
An empty result describes the supplied graph and coverage, not a safe-to-delete
verdict.

## Choose a guide

- [CLI and artifacts](https://github.com/TraceKite/tracekite/blob/main/docs/cli.md)
- [Python integration](https://github.com/TraceKite/tracekite/blob/main/docs/library.md)
- [Agent/MCP setup](https://github.com/TraceKite/tracekite/blob/main/docs/plugins-and-mcp-guide.md)
- [Browser app](https://github.com/TraceKite/tracekite/blob/main/docs/quickstart.md)
- [Features and limits](https://github.com/TraceKite/tracekite/blob/main/docs/features.md)

`tracekite ingest` sends committed code to a running app and needs
`pip install 'tracekite-core[server]'`. Optional Neo4j and HTML/CSS grammar
dependencies are available through the `neo4j` and `languages` extras.

Apache 2.0. [Source and documentation](https://github.com/TraceKite/tracekite).
