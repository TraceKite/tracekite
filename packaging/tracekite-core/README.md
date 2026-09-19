# tracekite-core

`tracekite-core` scans source repositories and establishes dependency edges only
when both sides meet on a deterministic key. Every returned edge includes
file-and-line evidence, while ambiguous signals are declined and counted.

The distribution contains the library and the `tracekite` CLI without requiring
FastAPI or Neo4j:

```bash
pip install tracekite-core
tracekite link /path/to/service-a /path/to/service-b
```

Use `tracekite mcp` to expose `services`, `consumers_of`, `trace`, and
`deprecations` over MCP stdio. With no path arguments, it scans the current
repository on the first graph query.

`tracekite ingest` talks to a running TraceKite server and needs the server
extra:

```bash
pip install 'tracekite-core[server]'
```

Documentation and source are available in the
[TraceKite repository](https://github.com/TraceKite/tracekite).
