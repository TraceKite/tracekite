# Run the TraceKite app

[Docs](README.md) · Next: [Using the views](using-the-views.md)

This walkthrough starts the web app and explores two public Spring Petclinic
repositories. The app reads their source; it does not start Petclinic.

## 1. Start the app

You need Git, OpenSSL, and Docker with Compose v2. Allow several GB of memory
for Neo4j and the build; larger repositories need more time and memory.

```bash
git clone https://github.com/TraceKite/tracekite.git
cd tracekite
./scripts/setup.sh
docker compose up -d --build
docker compose ps
```

`setup.sh` creates `.env` with generated database and redaction secrets. It
leaves an existing `.env` alone. Keep this file private.

Open <http://localhost:28080>. The API is at <http://localhost:28000>:

```bash
curl -fsS http://localhost:28000/health
```

Look for `"status":"ok"` and `"neo4j":"ok"`. If you changed the ports, use
those values instead. If a stack already exists, follow
[configuration](configuration.md#reuse-an-existing-stack) before starting another.

## 2. Ingest repositories

In the header, click **Ingest**, paste the first URL, leave the branch blank to
use the remote default, and submit. Repeat for the second URL:

```text
https://github.com/spring-petclinic/spring-petclinic-microservices
https://github.com/spring-petclinic/spring-petclinic-cloud
```

The progress card reports each submitted job. Ingestion writes the repository's
source graph; a successful ingest then queues a link run across the stored
repositories. **You do not need to press Rebuild after each ingest.**

Wait for both repositories to finish and for Service Map's **Rebuilding links**
message to disappear. A link run may take longer than parsing on a large estate.
A failed ingestion stays visible until dismissed.

Prefer a terminal? These requests queue the same jobs and return a `job_id`:

```bash
curl -fsS -X POST http://localhost:28000/api/repos/ingest \
  -H 'Content-Type: application/json' \
  -d '{"github_url":"https://github.com/spring-petclinic/spring-petclinic-microservices"}'

curl -fsS -X POST http://localhost:28000/api/repos/ingest \
  -H 'Content-Type: application/json' \
  -d '{"github_url":"https://github.com/spring-petclinic/spring-petclinic-cloud"}'
```

Check a job with `GET /api/jobs/JOB_ID` and link runs with
`GET /api/v2/links/status`. Queued (`202`) means accepted, not finished.
The [CLI guide](cli.md#send-code-to-the-app) also covers local Git uploads.

## 3. Follow one connection

1. Open the repository picker, select both Petclinic repositories, and click
   **Apply scope**. The same selection follows you across tabs.
2. Open **Service Map**, find `api-gateway`, and select it.
3. Open one of its **Calls** relationships. Read its confidence, detection
   signals, and source citations in the edge drawer.
4. Choose **Trace from here**, select `vets-service` as the destination, and
   click **Trace Paths**. Try **Code (Crossings)** to inspect an HTTP crossing.
5. Switch to **Repo** to search a file or endpoint and inspect its properties.
   Double-click a module to open its members; use **Back** to leave that level.

Expected: repository-backed services, gateway/service-call relationships, and
source citations. Exact counts depend on the upstream commits you ingested.
Trace shows paths derived from code and config, not recorded production traffic.

## 4. Keep it current

With one hosted repository selected in **Repo**, use **Refresh repository** to
fetch and replace its graph. Uploaded local repositories are updated by running
`tracekite ingest` again. Successful ingests and refreshes queue linking.
Remote Git pushes alone do not refresh the app.

Use **Delete repository** to open the app's confirmation dialog. Deletion is
queued; the progress card reports completion, and linking retires affected
relationships. This removes TraceKite's copy, not the upstream Git repository.

After changing linker configuration, queue a manual rebuild:

```bash
curl -fsS -X POST http://localhost:28000/api/v2/links/rebuild
```

Stop the app with `docker compose stop`; start it again with
`docker compose start`. Named volumes retain the graph and cloned sources.

## If the result is unexpected

| Symptom | Check |
|---|---|
| App will not start | `docker compose ps` and `docker compose logs --tail=100 backend neo4j`; required secrets must be set |
| Ingest failed | Read the job's `error`; verify URL, branch, allowed Git host, and access credentials |
| Links are stale | Inspect `/api/v2/links/status`. An active run finishes automatically; a failed run includes an error. Rebuild after resolving it |
| Service Map has no services | Confirm the selected repos declare service identities and linking completed. A library can have a populated Repo graph with no service map |
| Two repositories are unconnected | They may have no supported shared contract; check evidence, scope, and [coverage limits](design/coverage-gaps.md) |
| CLI/MCP sees different data | Those surfaces load their own source/artifact inputs, not the app's Neo4j graph |

More: [configuration](configuration.md) · [HTTP API](api.md) · [support](../SUPPORT.md).
