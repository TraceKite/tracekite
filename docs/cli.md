# CLI and portable artifacts

[Docs](README.md) · Next: [Change review](change-review.md) or [MCP](plugins-and-mcp-guide.md)

Most commands analyze local files without Docker or a database. `ingest` is
the exception: it sends code to a running TraceKite app.

## Install and run the demo

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Alternatively install with `pip install tracekite-core` in your Python environment.

```bash
uv tool install tracekite-core
git clone https://github.com/TraceKite/tracekite.git
cd tracekite
tracekite scan corpus/orders-service --repo-id orders-service
tracekite link corpus/orders-service corpus/billing-service
```

`scan` prints node/edge counts, claims, coverage, and absence information.
`link` scans both directories and prints services, resolved edges, and counters.
Look for `global:Service:orders-service → global:Service:billing-service`.
The demo is [synthetic source](../corpus/README.md), not a running application.

## Before scanning your own code

Generate a private redaction key once and keep the same key for related scans
and artifact comparisons. For example, in a shell session:

```bash
export GRAPH_HMAC_KEY="$(openssl rand -hex 32)"
```

Store it securely for later sessions; do not commit it. CLI scans otherwise
use a built-in local fallback, which is convenient for the public demo but is
not a private salt for sensitive configuration. The Python facade requires a
host-supplied key. See [security and privacy](security-and-privacy.md).

Pass one directory per repository. IDs default to directory basenames. Use
artifacts with distinct `--repo-id` values when two directories have the same
name. Source scans read the working tree, including uncommitted files that the
scanner admits; they do not clone URLs.

## Explain a connection

Copy the source and target IDs from a link result. For the demo:

```bash
tracekite explain corpus/orders-service corpus/billing-service \
  --edge global:Service:orders-service global:Service:billing-service
```

The explanation reports the derivation and citations for existing edges.
It does not create a missing connection.

## Save and reuse an artifact

A `.tracekite` file is a SQLite snapshot of one scan: nodes, edges, claims,
coverage, and revision metadata. No source checkout is needed to query its graph.
Use source control separately to open the cited source text.

From the demo checkout, capture the filenames printed by the commands:

```bash
orders_artifact=$(tracekite artifact corpus/orders-service \
  --repo-id orders-service --head-sha "$(git rev-parse HEAD)" --out ./tk-artifacts)
billing_artifact=$(tracekite artifact corpus/billing-service \
  --repo-id billing-service --head-sha "$(git rev-parse HEAD)" --out ./tk-artifacts)
tracekite mcp "$orders_artifact" "$billing_artifact"
```

The last command waits for MCP JSON-RPC on stdin. An agent client normally
starts it for you. Use [MCP setup](plugins-and-mcp-guide.md) for that workflow.
For real repositories, pass each repository's own commit to `--head-sha`.

Artifacts have content-derived filenames. Repeating `artifact` with unchanged
inputs reuses the existing snapshot. Use a fresh output directory after changing engine/configuration, the redaction
key, or desired revision metadata: 0.2.0 reuse checks source content only.
Restart long-running MCP/facade instances to load updated artifacts.

## Send code to the app

Install the optional HTTP client dependencies:

```bash
uv tool install 'tracekite-core[server]'
tracekite ingest https://github.com/spring-petclinic/spring-petclinic-microservices \
  --server http://localhost:28080
```

For your local Git repository:

```bash
tracekite ingest /absolute/path/to/my-repo --name my-repo \
  --server http://localhost:28080
```

Replace the absolute path first. Directory ingestion uploads **committed Git
content only**, even when invoked from a subdirectory; `--name` must be
lowercase. `--no-wait` returns after queuing. The normal command waits up to
30 minutes for ingestion, not for the following link run.

`--token` is a Git-host token, not a TraceKite API bearer token. In 0.2.0 the
CLI ingest client does not send API authentication headers; use the
[HTTP API](api.md) for an authenticated server. The shipped loopback Compose
stack has authentication disabled by default.

## Command reference

Use `tracekite COMMAND --help` for arguments. Global `--config-dir`, `--log`,
`--log-format`, and `--hmac-key` options go **before** the command.

| Command | Input and result |
|---|---|
| `tracekite scan` | One directory → scan counts, claims, coverage, absence |
| `tracekite link` | Source directories → linked graph JSON; does not accept artifacts |
| `tracekite explain` | Source directories + `--edge SOURCE TARGET` → existing edge explanation |
| `tracekite artifact` | One directory + `--out DIR` → artifact filename |
| `tracekite mcp` | Directories/artifacts → stdio server; default input is `.` |
| `tracekite ingest` | Git URL or local Git directory → server job; optional `--branch`, `--name`, `--no-wait` |
| `tracekite diff` | Two artifact files → added/removed nodes and edge changes |
| `tracekite history` | Oldest-to-newest artifacts → edge history; optional `--consumers-of ID` |
| `tracekite pr` | Complete `--base` and `--head` artifact sets → indexed dependency losses |
| `tracekite drift` | Artifacts → declared/observed differences; optional `--base` for changes over time |
| `tracekite deprecations` | Artifact estate → deprecated contracts and indexed consumers |
| `tracekite reverify` | Artifacts + `--repo-root DIR` → stale citations and proposed confidence downgrades |
| `tracekite suggest-aliases` | Artifacts → draft alias suggestions; applies nothing |
| `tracekite reviews` | Configured review decisions → labelled review data |
| `tracekite coverage` | Declared HTTP route/client coverage and reasons for declines |
| `tracekite resolvers` | Registered resolver order and phases |
| `tracekite health` | Engine configuration health; does not check the Docker server |
| `tracekite schema` | Published CLI report JSON Schemas |
| `tracekite install-skill` | Explicitly install agent instructions; repeat `--client` to select clients |

## Automation details

Most analysis commands print JSON to stdout and diagnostics to stderr. Exceptions
include `artifact` (a path), `mcp` (protocol messages), `ingest` (job progress),
`install-skill` (installation messages), and `pr --comment` (Markdown).

| Exit code | Meaning |
|---|---|
| `0` | Command completed; it is not a universal safety/completeness verdict |
| `1` from `diff` | Graph changes found |
| `1` from `pr` | The change was attributed a blocking indexed dependency loss |
| `1` from `drift` | Drift found |
| `1` from `ingest` | Job failed or waiting timed out; check the server job |
| `2` from `reverify` | No citation verified; check `--repo-root` |

`link` and `explain` accept `--now` for reproducible timestamps. `history`,
`pr`, `deprecations`, `reverify`, and `suggest-aliases` default to a fixed time;
pass an explicit `--now` when evaluating time-sensitive annotations.
