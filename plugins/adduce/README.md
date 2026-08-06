# Adduce Agent Plugin

This one plugin source supports Claude Code, Codex, and Kimi Code. It bundles
the Adduce skill with an MCP server declaration; each client reads its own
manifest and ignores the others.

Every relationship returned by the MCP tools carries the evidence stored in
the graph. An empty or declined answer means Adduce did not establish the
relationship.

## Prerequisite

Install the local Adduce CLI before enabling the plugin:

```bash
git clone https://github.com/adduce-labs/adduce.git
cd adduce
uv tool install .
adduce --help
```

The bundled MCP command is `adduce mcp` with no explicit path. It scans the
client's current repository lazily on the first graph query, then answers from
that in-memory graph for the rest of the session.

## Claude Code

For a development session:

```bash
claude --plugin-dir ./plugins/adduce
```

To exercise the repository marketplace locally:

```bash
claude plugin marketplace add .
claude plugin install adduce@adduce-labs
```

## Codex

Add the repository marketplace, install the plugin, and start a new session:

```bash
codex plugin marketplace add .
codex plugin add adduce@adduce-labs
```

## Kimi Code

Start Kimi from this repository, then run these commands in the TUI:

```text
/plugins install ./plugins/adduce
/reload
```

Kimi plugin support must be present in the installed release. If `/plugins`
is unavailable, update Kimi before using this bundle.

## Multiple repositories

The bundled server intentionally defaults to the current repository. For an
estate, register a separate MCP server with every absolute source or artifact
path:

```bash
claude mcp add --scope user adduce-estate -- adduce mcp \
  /path/to/orders /path/to/billing /path/to/gateway

codex mcp add adduce-estate -- adduce mcp \
  /path/to/orders /path/to/billing /path/to/gateway
```

Kimi Code users can add the same command and arguments with `/mcp-config`.

## Verify

Ask the client to list services first. Then use an exact service ID or one
unambiguous service name returned by that tool:

```text
What services does Adduce know about?
Who depends on the billing service?
Trace the active path from the gateway service to billing.
```

The MCP surface exposes `services`, `consumers_of`, `trace`, and
`deprecations`. See the
[agent integration guide](https://github.com/adduce-labs/adduce/blob/main/docs/plugins-and-mcp-guide.md)
for argument and evidence semantics.
