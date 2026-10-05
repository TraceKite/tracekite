# Connect an AI client through MCP

[Docs](README.md) · Next: [Tool reference](mcp-tools.md)

MCP lets your coding agent ask TraceKite for services, callers, paths, neighbors,
subgraphs, and source evidence. TraceKite runs locally over **stdio**. It does
not need Docker, query the app database, or watch files for changes.

## 1. Install the CLI

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv tool install tracekite-core
tracekite --help
```

The client must be able to find `tracekite` on its PATH. If it cannot, use the
absolute executable path in its MCP configuration.

## 2. Choose the input repositories

Use one absolute directory per repository, or one `.tracekite` artifact per
repository. Replace the example paths before registering:

```bash
tracekite mcp /absolute/path/orders /absolute/path/billing
```

This command waits for protocol messages; it is not an interactive shell.
With no paths, it scans the client's working directory. A parent directory is
not automatically expanded into separate repositories. Duplicate repo IDs are
rejected; use artifacts with distinct IDs when directory basenames collide.

The handshake and tool list are immediate. The **first graph query** scans or
loads all inputs and links them. Later calls reuse that in-memory snapshot.
For a large estate, build [artifacts](cli.md#save-and-reuse-an-artifact) first.
Restart the MCP server after rebuilding them or changing source.

## 3. Register with your client

Use one of the following, then start a new client session. For sensitive source,
configure a private `GRAPH_HMAC_KEY` in the child process environment as described
in [the CLI guide](cli.md#before-scanning-your-own-code).

### Codex

```bash
codex mcp add tracekite -- tracekite mcp \
  /absolute/path/orders /absolute/path/billing
codex mcp list
```

Settings live in `~/.codex/config.toml`. For environment forwarding or a longer
first-query timeout, see the [official MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
For example, `env_vars = ["GRAPH_HMAC_KEY"]` under this server's table forwards
an already-set shell variable; GUI clients may have a different environment.

### Claude Code

```bash
claude mcp add --transport stdio --scope user tracekite -- tracekite mcp \
  /absolute/path/orders /absolute/path/billing
claude mcp list
```

Use project scope if the configuration should belong to one workspace. See the
[official MCP guide](https://code.claude.com/docs/en/mcp) for environment options.

### Cursor and clients using `mcpServers` JSON

Add this entry using your client's MCP settings, replacing the paths:

```json
{
  "mcpServers": {
    "tracekite": {
      "command": "tracekite",
      "args": ["mcp", "/absolute/path/orders", "/absolute/path/billing"]
    }
  }
}
```

Cursor uses `~/.cursor/mcp.json` for user configuration; see its
[MCP guide](https://cursor.com/docs/mcp). Merge the entry into an existing file
rather than replacing other servers.

### Kimi Code

Run `/mcp-config` in the TUI and register the command/arguments above. Current
Kimi Code uses `~/.kimi-code/mcp.json` or project `.kimi-code/mcp.json`; `/mcp`
shows connection status. Older Kimi CLI versions use different paths/commands.
See the [current Kimi Code guide](https://moonshotai.github.io/kimi-code/en/customization/mcp.html).

Other stdio-capable clients can use the same command and arguments through their
own configuration UI. Remote-only clients need a host-provided adapter;
TraceKite 0.2.0 does not provide an HTTP MCP endpoint.

## 4. Verify the connection

Ask: “Use TraceKite to list services and show the repository IDs.” Then ask for
`node` on one returned ID, followed by `consumers_of` or `neighbors`.
For a repeatable result use the [included demo](../corpus/README.md).

Expect all nine tools in the client: `services`, `node`, `search`, `consumers_of`,
`trace`, `neighbors`, `impact`, `subgraph`, and `deprecations`. Read their
[arguments and limits](mcp-tools.md) and [answer contract](answers.md).

## Optional: skill or plugin

A **skill** gives the agent usage instructions. An **MCP server** provides tools.
A **plugin** bundles both. Installing a skill alone does not connect MCP.

```bash
tracekite install-skill --client codex --client claude
```

The installer writes supported global skill paths and refuses to overwrite a
different existing file. It does not edit MCP configuration. In 0.2.0 its Kimi
target is the legacy `~/.kimi/skills/tracekite/`; use the
[plugin](../plugins/tracekite/README.md) or your current client's documented
skill installation path for newer Kimi Code. Antigravity is also an installer
target; verify its paths against the installed client version.

The [cross-client plugin guide](../plugins/tracekite/README.md) covers the local
bundle. The repository's `scripts/install.sh` installs the source CLI plus
selected skills; `scripts/setup.sh` prepares Docker. They serve different tasks.

## Troubleshooting

| Problem | Action |
|---|---|
| Tools do not appear | Check executable PATH, client MCP status, and restart the session |
| First query times out | Prebuild artifacts or increase the client's tool-call timeout |
| Services are empty | Search source nodes; the inputs may have no supported service declarations |
| Node is unknown or ambiguous | Use `search`/`services` and retry an exact ID |
| Old results after edits | Restart the MCP server; regenerate artifacts in a fresh output directory after engine/config changes |
| Different result from browser | Check input repos/revisions; MCP does not query the app's Neo4j graph |
