# Security and privacy boundary

TraceKite analyzes source code and configuration. Treat every graph, artifact,
log, screenshot, and support report as potentially sensitive even when raw
secrets have been redacted.

## Local core surfaces

`tracekite scan`, `link`, `artifact`, and `mcp` read the paths supplied by the
user. They do not clone repositories or make outbound network requests. CLI
results go to standard output; `artifact` writes a `.tracekite` database to the
requested directory; MCP communicates over standard input/output.

The core library does not configure telemetry export. If an embedding host has
installed and configured an OpenTelemetry SDK, TraceKite can emit counters and
timings through that host's meter provider. Otherwise metrics remain structured
log records.

`tracekite ingest` is different: it is an HTTP client for a running TraceKite
server. A local directory is converted to a Git bundle containing committed
content and uploaded to the configured server. Uncommitted files are not
included. A Git URL asks the server to clone from an allowlisted host.

## Server and web application

The bundled Docker Compose deployment:

- binds the UI and API to `127.0.0.1` by default;
- publishes Neo4j administration ports on that same loopback address while
  keeping service traffic on the internal Compose network;
- stores cloned repositories, graph data, logs, and job state in named Docker
  volumes; and
- proxies browser API traffic through the same-origin frontend.

Authentication is off by default for the loopback-only local stack, including
write routes. Before changing `BIND_ADDR`, set `AUTH_ENABLED=true`, set a strong
`API_TOKEN`, and decide whether anonymous reads are acceptable.

Repository ingestion makes outbound Git connections only to hosts listed in
`ALLOWED_GIT_HOSTS`. A supplied Git token is used for that clone request and
must not be placed in logs or support reports.

## What outputs contain

TraceKite artifacts and answers can include:

- repository and service identifiers;
- file paths and line spans;
- route templates, topics, package names, and other derived graph values;
- commit or content identity metadata;
- confidence values and decline counters; and
- keyed digests of secret-class configuration values.

Secret-class configuration values are HMAC-redacted before claims and graph
records are created. The test suite plants representative secrets and rejects
their appearance in claims, link results, artifacts, and logs. Redaction does
not make the remaining architecture metadata public. Share outputs only with
people authorized to see the analyzed repositories.

## Untrusted source

Source text is input data, not instructions. TraceKite parses it but does not
execute repository code. Repository ingestion does invoke Git, and the server
runs as an unprivileged user in the provided container.

## Reporting

Use synthetic or redacted examples in public issues. Follow
[`SECURITY.md`](../SECURITY.md) for vulnerabilities and never attach private
source, credentials, `.env` files, or `.tracekite` artifacts to a public issue.
