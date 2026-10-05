# TraceKite agent plugin

[Documentation](../../docs/README.md) · [MCP setup](../../docs/plugins-and-mcp-guide.md)

This local plugin bundle contains the same TraceKite skill and stdio MCP command
in manifests for Claude Code, Codex, and Kimi Code. A skill supplies instructions;
MCP supplies graph tools. The plugin does not include the CLI executable.

## Install the CLI first

Requires Python 3.13+ and uv:

```bash
uv tool install tracekite-core
tracekite --help
git clone https://github.com/TraceKite/tracekite.git
cd tracekite
```

## Load the bundle

Choose the workflow your installed client supports:

| Client | Local workflow, from this checkout |
|---|---|
| Claude Code | `claude --plugin-dir ./plugins/tracekite` for a development session |
| Codex | `codex plugin marketplace add .`, then `codex plugin add tracekite@tracekite` |
| Kimi Code | `/plugins install ./plugins/tracekite` in the TUI, then start a new session |

Plugin support and commands vary by client version. Check its help if unavailable;
[direct MCP registration](../../docs/plugins-and-mcp-guide.md#3-register-with-your-client)
is the simpler fallback and supports explicit multi-repo paths.

## Select the intended source

The bundled server runs `tracekite mcp` with no input path. It scans the client's
working directory on the first graph query. Launch the client from the repository
you want analyzed; installing this bundle from TraceKite's checkout does not make
it automatically discover your other projects.

For multiple repositories, register a separate server such as `tracekite-estate`
with one absolute path per repo or artifact. Do not edit an installed plugin
cache to encode local paths. Configure a private redaction key in the MCP process
environment before analyzing sensitive source.

## Verify

Ask the agent to list TraceKite services, describe an exact returned ID, and then
show its consumers with citations. The nine tools are `services`, `node`, `search`,
`consumers_of`, `trace`, `neighbors`, `impact`, `subgraph`, and `deprecations`.
See [query semantics](../../docs/mcp-tools.md) for bounds and direction.

The snapshot stays in memory for the session. Restart after source/artifact
changes. The server does not use the Docker app's Neo4j graph, and an empty answer
is not permission to delete code.
