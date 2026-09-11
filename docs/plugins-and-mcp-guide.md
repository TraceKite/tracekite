# Agent and MCP integration

Evigraph can scan source directories or load portable `.evigraph` artifacts, link
their claims once at startup, and answer MCP requests over stdio. Client
registration is explicit because each client owns a different configuration
format.

## Install the CLI and skill

From this checkout:

```bash
uv tool install .
evigraph install-skill
```

`install-skill` supports `claude`, `codex`, `kimi`, and
`antigravity`. Repeat `--client` to select more than one:

```bash
evigraph install-skill --client codex --client kimi
```

The installer writes only published global skill locations:

| Client | Skill path |
|---|---|
| Claude Code | `~/.claude/skills/evigraph/SKILL.md` |
| Codex | `~/.agents/skills/evigraph/SKILL.md` |
| Kimi | `~/.kimi/skills/evigraph/SKILL.md` |
| Antigravity | `~/.gemini/config/skills/evigraph/SKILL.md` |

An existing, different file is never overwritten. MCP configuration is never
changed by this command.

## Or install the agent plugin

The repository's [`plugins/evigraph/`](../plugins/evigraph/) directory is one
cross-client plugin source. It carries separate Claude Code, Codex, and Kimi
manifests around the same skill. Its default MCP command is `evigraph mcp`, which
scans the client's current repository on the first graph query.

For multiple repositories, register a separate MCP server with every absolute
path instead of editing an installed plugin cache. The plugin README contains
the current client-specific marketplace and registration commands.

## Choose MCP inputs

Pass each repository as its own source directory:

```bash
evigraph mcp /absolute/path/orders /absolute/path/billing
```

Source directories are fully scanned when the server starts. A parent
directory is not treated as a collection of repositories.

For repeatable CI or faster startup, create one artifact per repository and
pass the resulting filenames:

```bash
evigraph artifact /absolute/path/orders --repo-id orders --out ./artifacts
evigraph artifact /absolute/path/billing --repo-id billing --out ./artifacts
evigraph mcp ./artifacts/orders-<digest>.evigraph \
  ./artifacts/billing-<digest>.evigraph
```

Inputs with the same repository ID are rejected rather than merged
arbitrarily.

## Register the stdio server

Use absolute repository or artifact paths in persistent client configuration.

### Codex

```bash
codex mcp add evigraph -- evigraph mcp \
  /absolute/path/orders /absolute/path/billing
```

Codex stores user configuration in `~/.codex/config.toml`. See the
[Codex MCP documentation](https://developers.openai.com/codex/mcp/).

### Claude Code

```bash
claude mcp add --scope user evigraph -- evigraph mcp \
  /absolute/path/orders /absolute/path/billing
```

See the
[Claude Code MCP documentation](https://docs.anthropic.com/en/docs/claude-code/mcp).

### Kimi CLI

```bash
kimi mcp add --transport stdio evigraph -- evigraph mcp \
  /absolute/path/orders /absolute/path/billing
```

Kimi's global MCP configuration is `~/.kimi/mcp.json`. See the
[Kimi CLI MCP guide](https://moonshotai.github.io/kimi-cli/en/customization/mcp.html).

### Cursor

Add the server to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "evigraph": {
      "command": "evigraph",
      "args": [
        "mcp",
        "/absolute/path/orders",
        "/absolute/path/billing"
      ]
    }
  }
}
```

See [Cursor's MCP documentation](https://docs.cursor.com/context/model-context-protocol).

### Antigravity

Add the same `mcpServers.evigraph` command and arguments to
`~/.gemini/config/mcp_config.json`. Antigravity uses
`~/.gemini/config/skills` for global skills.

## Tool contract

| Tool | Answer |
|---|---|
| `services()` | repository-backed services and artifact commit metadata |
| `consumers_of(node_id)` | active incoming edges with file-and-line evidence |
| `trace(from_id, to_id, max_hops)` | bounded active paths between exact node IDs |
| `deprecations()` | deprecated contracts with active consumers |

Friendly service names resolve only when they identify one known node. An
ambiguous name is returned as a decline with candidates; callers should retry
with an exact ID.

## Troubleshooting

- Run `evigraph --help` to verify the executable is on the client's PATH.
- Run `evigraph mcp ...` in a terminal and send newline-delimited JSON-RPC only
  when debugging the transport; normal clients manage stdio themselves.
- If two inputs share a basename, create artifacts with distinct
  `--repo-id` values.
- Rebuild artifacts after source changes. The MCP server loads its inputs once
  and does not watch the filesystem.
