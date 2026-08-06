# adduce-core

`adduce-core` scans source repositories and establishes dependency edges only
when both sides meet on a deterministic key. Every returned edge includes
file-and-line evidence, while ambiguous signals are declined and counted.

The distribution contains the library and the `adduce` CLI without requiring
FastAPI or Neo4j:

```bash
pip install adduce-core
adduce link /path/to/service-a /path/to/service-b
```

Use `adduce mcp` to expose `services`, `consumers_of`, `trace`, and
`deprecations` over MCP stdio. With no path arguments, it scans the current
repository on the first graph query.

Documentation and source are available in the
[Adduce repository](https://github.com/adduce-labs/adduce).
