# Rename migration

The current distribution, Python package, command, Compose project, environment
variables, plugin, and skill are all named `tracekite` or `TraceKite`. The
repository intentionally carries no compatibility aliases for earlier names.

## CLI and Python

Remove any locally installed pre-TraceKite tool, then install the current
distribution:

```bash
uv tool list
uv tool uninstall <legacy-distribution>
uv tool install tracekite-core
tracekite --help
```

Update Python imports to `tracekite`. Existing `.tracekite` artifacts are
versioned and are read through the normal artifact compatibility checks; do not
rename or edit their contents.

Global skill installers do not overwrite an existing skill. List your client's
global skill directory, remove an obsolete legacy entry only after reviewing
it, then run:

```bash
tracekite install-skill
```

MCP client configuration is never edited by the installer. Remove obsolete
server entries manually and register the command documented in
[`docs/plugins-and-mcp-guide.md`](plugins-and-mcp-guide.md).

## Docker volumes

Changing the Compose project name changes Docker's implicit volume names. This
can make an existing graph appear empty even though its volumes still exist.
Do not run `docker compose down --volumes` during migration.

First stop the old stack without deleting volumes and list the existing names:

```bash
docker compose -p <legacy-compose-project> down
docker volume ls
```

For each volume you want to retain, set the matching override in `.env`:

```dotenv
TRACEKITE_NEO4J_DATA_VOLUME=<existing-neo4j-data-volume>
TRACEKITE_NEO4J_LOGS_VOLUME=<existing-neo4j-logs-volume>
TRACEKITE_REPO_WORKSPACE_VOLUME=<existing-repository-volume>
TRACEKITE_BACKEND_VAR_VOLUME=<existing-backend-state-volume>
```

Then start TraceKite and verify the repositories. A volume selected by an
override remains the active data store; do not delete it. New installations
leave these variables unset and use stable `tracekite_*` names.

Environment variables from older installations are not read. Compare the old
file with `.env.example`, copy values deliberately, and generate a new
`GRAPH_HMAC_KEY` only if retaining joinability with prior redacted values is
not required.

## Tested release platforms

Release CI validates the core wheel and source distribution on CPython 3.13,
the application container on CPython 3.14, and the web build on Node.js 22,
all on Ubuntu x86_64. Maintainer validation also covers the core distribution
on macOS arm64. Windows is not currently a release-tested platform.
