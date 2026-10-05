# HTTP API

[Docs](README.md) · [Configuration](configuration.md) · [Graph model](graph-model.md)

This API reads and manages the Docker app's Neo4j graph. It is separate from
MCP stdio and from the in-memory Python facade.

Default direct URL: `http://localhost:28000`. The frontend also proxies `/api`
and `/health` at `http://localhost:28080`. See the backend's `/docs` interactive
reference or the [generated OpenAPI file](../lib/api-spec/openapi.yaml) for all
request fields and limits. The route source remains authoritative.

## Jobs and freshness

Ingest, refresh, delete, and link requests return HTTP `202` with a `job_id`.
Poll `GET /api/jobs/{job_id}` until `status` is `completed` or `failed`; inspect
`message`, `progress`, and `error`. Do not treat a queued response as success.

Successful ingestion replaces the repository graph and queues linking.
`GET /api/v2/links/status` returns recent runs, the latest run, and stale-repo
warnings. Link-run status uses `running`, `done`, and `failed`; job status uses
`queued`, `running`, `completed`, and `failed`.

```bash
curl -fsS http://localhost:28000/health
curl -fsS http://localhost:28000/api/repos
curl -fsS http://localhost:28000/api/v2/links/status
```

A completed ingest can precede completion of its automatic link run. Deleted
repository rollups also need the queued link run to retire their old edges.

## Repository and source graph endpoints

| Method and path | Use |
|---|---|
| `POST /api/repos/ingest` | Queue a hosted Git URL; optional branch/token |
| `POST /api/repos/ingest-upload` | Upload a Git bundle with multipart `file`, `name`, optional `branch` |
| `GET /api/repos` | Repository list, counts, ingestion state, coverage/revision metadata |
| `GET /api/repos/{repo_id}` | One repository summary |
| `POST /api/repos/{repo_id}/refresh` | Re-clone a hosted repo; uploaded repos must be uploaded again |
| `DELETE /api/repos/{repo_id}` | Queue deletion of TraceKite's stored copy |
| `GET /api/jobs/{job_id}` | Job progress/result |
| `GET /api/repos/{repo_id}/graph` | Bounded source graph; choose `view`, `limit`, types, search, or impact focus |
| `GET /api/repos/{repo_id}/search?q=...` | Ranked source-node lookup |
| `GET /api/repos/{repo_id}/nodes/{node_id}` | Properties, incoming/outgoing relationships, neighbors |
| `GET /api/repos/{repo_id}/nodes/{node_id}/neighbors` | Bounded local neighborhood |

URL-encode node IDs and query values. Repository IDs come from the repo list;
MCP source-directory IDs can differ from server IDs for the same code.

## Estate map and linking

| Method and path | Use |
|---|---|
| `GET /api/v2/service-map` | Services/topic relationships; `min_confidence`, `limit` (up to 500 edges) |
| `GET /api/v2/service-map/aggregate` | Aggregate service connections by `domain` or `team` |
| `GET /api/v2/code-bridges?repos=a,b` | Call/contract bridges with the source endpoints included |
| `GET /api/v2/trace` | `from_service`, `to_service`, confidence, hops, path count, Service/Code altitude |
| `POST /api/v2/links/rebuild` | Full estate relink, normally queued automatically after ingestion |
| `POST /api/v2/links/delta` | Skip if claim fingerprints are unchanged; otherwise recompute the full link result |
| `GET /api/v2/links/status` | Run ledger and stale-repo warnings |
| `GET /api/config` | UI scope/detail limits |
| `GET /health` | API/database health and authentication posture |

The map API returns an estate-wide result. The browser applies repository scope
to it. A per-repo graph never by itself supplies cross-repo links. Check map
`truncated` and result budgets; the UI's scope cap is not a database size limit.

## Specialized queries

These are HTTP features, not additional browser tabs or MCP tools:

| GET path | Required query / result |
|---|---|
| `/api/v2/impact/library` | `key=pkg:npm/@acme/client`; publishers, dependent repos, versions, skew |
| `/api/v2/impact/repo/{repo_id}` | Published libraries and their consumers; **library-only**, not HTTP blast radius |
| `/api/v2/topics` | Topic keys and counts |
| `/api/v2/topics/chain` | `key=...`; supported publishers, consumers, fan-out |
| `/api/v2/config/ownership` | `name=DATABASE_URL`; config definitions/read sites and available owners |
| `/api/v2/links/deprecated` | Deprecated HTTP contracts and no-invocation candidates |
| `/api/v2/links/review` | Candidate edges and named resolver declines |

Example (replace the illustrative package key with one in your estate):

```bash
curl -fsSG http://localhost:28000/api/v2/impact/library \
  --data-urlencode 'key=pkg:npm/@acme/client'
```

No-invocation candidates are a narrow graph query, not proof of unused endpoints.
In 0.2.0 that query checks `INVOKES` only; inspect `UI_CALLS` and coverage too.

`POST /api/v2/links/review/decide` changes a relationship's status and persists
a promotion/rejection. Review the exact source/type/target triple and evidence
before using it; consult OpenAPI for its body. Alias suggestions are a separate
read-only CLI report and are never applied automatically.

## Authentication and errors

Compose disables auth for the default loopback-only stack. When enabled, send
`Authorization: Bearer $API_TOKEN`; read access depends on
`ALLOW_ANONYMOUS_READS`. `--token` on CLI `ingest` is a Git credential and cannot
substitute for this header.

Invalid input, unknown targets, auth failures, and job failures are different
states. Read the HTTP response and the job's eventual result. See
[configuration](configuration.md) and [reading answers](answers.md).
