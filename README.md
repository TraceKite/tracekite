# Adduce

*adduce* (v.) — to cite as evidence in support of a claim.

Point it at your repositories. It builds a typed graph of what your services
actually are and how they actually reach each other — and every edge cites the
file and line it came from.

**The problem.** You are about to change an endpoint. You grep for its path
and find nothing, because the caller builds the URL from a config value. You
ask in Slack and someone remembers one consumer. You ship, and a service
nobody remembered breaks — one owned by another team, in another repository,
that reached you through a gateway that rewrote the path on the way.

Nothing in your own repository could have told you. The call is a string in a
config file, the route is an annotation in a second repo, and the host is an
environment variable set by a Helm chart in a third. No single repository
holds both halves of the story.

**The question this answers: if I change this endpoint, who breaks?** — with a
file and line for every answer, so you can check it rather than trust it.

```
customers-service ──GET /api/vets──▶ vets-service
   evidence: src/clients/VetsClient.java:42  →  VetsResource.java:31
   confidence 0.94   via: http_route + compose_env_host
```

## Isn't this Backstage? Or Sourcegraph? Or a service map?

Reasonable question — those are the tools most teams reach for, and each
answers a different part of this.

| | Where its graph comes from | What it cannot tell you |
|---|---|---|
| **Service catalogs** (Backstage, Cortex, OpsLevel) | descriptor files people write and maintain by hand | whether the code still matches what was declared — the catalog is a statement of intent, and it drifts the first time someone ships without updating it |
| **Runtime service maps** (Datadog, Kiali, Jaeger) | traces emitted by instrumented services in production | what *can* happen, only what *did* — a path not exercised in the observed window is invisible, and none of it exists before you deploy |
| **Code intelligence** (Sourcegraph, LSIF/SCIP) | symbol definitions and references | that a compose env var wires service A to service B, or that a gateway strips `/api/vet` before forwarding to `/vets` — these are contracts, not symbols |

### And tools that turn code into a graph?

There is a whole family of them — dependency-cruiser, madge, jdeps, pydeps,
code2flow, AST-to-Neo4j importers, SCIP/LSIF indexes. They graph what is
**lexically present in the code**: this file imports that one, this function
calls that function. The edge exists because one symbol names another.

Adduce's edges are not present in any source file. Here is a real call, and
the endpoint that serves it:

```python
# projects/foyer/.../registry_projection_cache.py:75          (Python)
callers_resp = await self._http.get(f"{self._registry_url}/v1/callers")
```
```go
// projects/capability-registry/internal/registry/routes.go:34  (Go)
mux.HandleFunc("GET /v1/callers", s.handleCallers)
```

No symbol in the first file names the second service. `_registry_url` is a
constructor parameter, injected from configuration. The strongest edge any AST
tool can draw here is *`_try_fetch` → `httpx.AsyncClient.get`* — it terminates
at the HTTP library, which is exactly where the interesting part begins. And
no single AST spans Python and Go anyway.

The connection exists only when three separate artifacts are joined: the call
site with its path template, the environment binding that says what
`_registry_url` points at, and a route registration written in another
language in another module.

**That is the distinction: syntactic reachability versus contract
rendezvous.** A code-graph tool answers "what does this code refer to".
Adduce answers "what does this system talk to" — and those two diverge
precisely at the process boundary, which is where a distributed system lives.

Measured on the corpus here: of **141** service-level connections in the
graph, **none** could be derived from source code alone. Every one required
evidence from outside it — a compose file, a Kubernetes manifest, a gateway
route table, or an environment binding. That is not a tuning difference; it
is a different kind of graph.

Adduce takes the third position: **derived from code and config rather than
declared, static rather than runtime, and at the altitude of service contracts
rather than symbols.** It answers "if I change this endpoint, who breaks?"
from a git clone, before anything is deployed, with a file and line behind
every claim.

**Where the others win, and it is worth being clear about it:**

- A runtime map sees calls this cannot: reflection, dynamic dispatch, anything
  assembled at runtime. On one estate measured here, static extraction found
  56 of 68 outbound HTTP call sites. Use both if you have both.
- A catalog carries ownership, lifecycle and on-call metadata that simply is
  not in the code. This infers ownership only where CODEOWNERS or a catalog
  file already says so.
- Sourcegraph is far better at "who calls this function". Different altitude,
  different question.

The honest summary: this is the tool for the window between writing code and
running it in production, and for the question a catalog can only answer if
somebody remembered to update it.

## Installation & Interfaces

Adduce is available as a **standalone CLI tool** (`adduce`), an **embeddable Python library** (`adduce-core`), and a **full Web Application** (`docker compose up`).

| Interface | Installation & Execution | Primary Use Case |
|---|---|---|
| **Standalone CLI Tool** | `uv tool install .` $\rightarrow$ `adduce link ...` | Terminal graph queries, PR impact checks, and MCP stdio |
| **Embeddable Library** | `pip install dist/adduce_core-*.whl` | Embed `scan()` and `link()` into Python CI scripts without a server |
| **Full Web Application** | `docker compose up -d` | Grouped 2D/3D code exploration, Service Map and Trace UI |

### 1. One-Line Setup

The interactive installer builds the CLI tool, provisions global AI agent
skills, and leaves MCP client configuration untouched:

```bash
git clone https://github.com/adduce-labs/adduce.git
cd adduce
./scripts/install.sh            # shows plan, asks Y/n, then installs
```

Pass `--yes` to skip the prompt (CI), or target a single client:

```bash
./scripts/install.sh --claude    # Claude Code only
./scripts/install.sh --codex     # OpenAI Codex only
```

Or install manually without the script:

```bash
uv tool install .
adduce install-skill             # all clients, or --client claude
adduce --help
```

> **Agent plugin** — The cross-client [Adduce plugin](plugins/adduce/)
> bundles the skill and MCP server declarations for Claude Code, Codex, and
> Kimi Code. Its README has verified setup commands for each client.

### 2. Basic CLI Commands

```bash
# Link local repositories and print JSON graph payload
adduce link path/to/repo-a path/to/repo-b

# Compare complete base and head artifact sets
adduce pr --base base/orders-<digest>.adduce \
  --head head/orders-<digest>.adduce --changed-repo orders

# Serve source repositories over MCP stdio
adduce mcp /absolute/path/repo-a /absolute/path/repo-b
```

### 3. As an Embeddable Core Library (`adduce-core`)

No container, no database. Install the pure engine on its own:

```bash
uv build --wheel --project packaging/adduce-core --out-dir dist
pip install dist/adduce_core-0.1.0-py3-none-any.whl
```

See [Developer use cases](docs/use-cases.md#embed-the-engine) for a direct
embedding example.

Then scan repositories and join them in memory:

```bash
python -m adduce.cli link path/to/repo-a path/to/repo-b
```

```json
{ "wire_version": "1.0.0",
  "claims_loaded": 7,
  "edges": [ { "type": "CALLS_SERVICE", "confidence": 0.94,
               "source": "...", "target": "...",
               "evidence": ["src/clients/VetsClient.java:42"] } ],
  "counters": { "r7.ambiguous_host": 3, "r7.fanout_exceeded": 1 } }
```

`counters` ships with every answer on purpose: a decline is recorded data, not
silence. `python -m adduce.cli schema` prints the JSON Schema those payloads
validate against — published under [`schemas/`](schemas/) and frozen, so a
non-Python consumer can validate without a binding.

In Python, the same two calls the CLI makes:

```python
from adduce import engine_config
from adduce.db.memory_store import InMemoryLinkerStore
from adduce.services.linker.engine import link
from adduce.services.scan import scan

engine_config.configure(graph_hmac_key="your-key")   # no env, no server

store = InMemoryLinkerStore([scan(path, repo_id) for repo_id, path in repos])
result = link(store.load_claims())   # pure: edges, evidence, declines
host.write(result.edges)             # you own persistence, or keep none
```

**Status.** The engine runs with no server and no database — enforced by a
test that blocks `fastapi` and `neo4j` from importing at all, not merely
checks they are absent. The `adduce-core` wheel builds from
[`packaging/adduce-core`](packaging/adduce-core) and installs into a clean
environment pulling neither; `scan()` and `link()` both work from it. It
installs one top-level package, `adduce`, so it coexists with a host that
has its own `app/` — a test pins that. It is not yet published to PyPI.

## Quickstart

Requires Docker and about 4 GB of free memory.

```bash
git clone https://github.com/adduce-labs/adduce.git
cd adduce
./scripts/setup.sh          # generates .env with fresh secrets
docker compose up -d --build
```

Open <http://localhost:28080>, then ingest two related repositories — the
interesting views need services that actually talk to each other:

```bash
curl -X POST http://localhost:28000/api/repos/ingest \
  -H 'Content-Type: application/json' \
  -d '{"github_url":"https://github.com/spring-petclinic/spring-petclinic-microservices"}'

curl -X POST http://localhost:28000/api/repos/ingest \
  -H 'Content-Type: application/json' \
  -d '{"github_url":"https://github.com/spring-petclinic/spring-petclinic-cloud"}'
```

Then build the links between them. **Ingestion finds facts; linking connects
them** — until you run this, there are no cross-repository edges:

```bash
curl -X POST http://localhost:28000/api/v2/links/rebuild
```

### Did it work?

Open **Service Map**. With both repositories ingested you should see around
**16 services** and, in the sidebar, `Gateway route 4` alongside a non-zero
`Service call` count. Select `api-gateway`: it lists `customers-service`,
`discovery-server`, `vets-service` and others under **Calls**, each with a
confidence. Click one to see the file and line behind it.

If Service Map is empty, the link run has not happened — rerun the command
above.

### A demo corpus that shows the point

Public, related, and exercising different join mechanisms:

| Repository | What it demonstrates |
|---|---|
| `spring-petclinic/spring-petclinic-microservices` | compose, Spring Cloud Gateway routes, cross-repo unification |
| `spring-petclinic/spring-petclinic-cloud` | the same services under a different topology |
| `confluentinc/kafka-streams-examples` | message topics as a join key |
| `grpc-ecosystem/grpc-gateway` | protobuf service definitions |

**Next:** [Using the views](docs/using-the-views.md) — the three views, the
repository picker, search, highlighting, and how module boundaries are drawn.

## How it works

The scattered evidence above is why this cannot be answered by analysing one
repository, and why the answer must be assembled rather than read off.

So the graph is not built by guessing. Ingestion emits **claims** — "this file
provides `GET /api/vets`", "this compose service consumes host `vets-service`" —
and a separate linker resolves claims into edges only when two independent
claims rendezvous on the same key. Fifteen resolvers cover different join
mechanisms: compose topology, Kubernetes, gateway routes, HTTP, gRPC, GraphQL,
message topics, packages, datasets, environment indirection, ownership,
webhooks, and one operation exposed over several transports.

Three rules keep it honest, and they are the whole design:

- **Decline, don't guess.** When a name is ambiguous the resolver refuses to
  link and increments a counter. Unlinked signals are stored and visible, so a
  gap is a reviewable fact rather than a silent absence.
- **Evidence or it didn't happen.** Every edge carries `file:line` provenance
  and a confidence in 0.6–0.99. Nothing is asserted that you cannot click
  through and read.
- **Honest splits over false merges.** Two services genuinely named `api` stay
  two scope-qualified nodes. Cross-scope unification needs two corroborating
  signals; generic names never unify on name alone.

## The CLI

Every command works on the library alone — no server, no database — and prints
JSON on stdout so it pipes. `--now` fixes the clock wherever a command has a
time dimension, which is what makes two runs diffable.

**Look at one repository, or a whole estate**

| Command | Answers |
|---|---|
| `adduce scan <path>` | what claims one repository emits |
| `adduce link <path>...` | the edges several repositories produce together |
| `adduce artifact <path> --out DIR` | scan into a content-addressed `.adduce` file, the unit CI publishes |
| `adduce explain <path>... --edge SRC DST` | why one edge exists — the resolver, the tier, the receipts |

**Ask the graph questions**

| Command | Answers |
|---|---|
| `adduce mcp <artifact>...` | serve the graph to an agent over MCP stdio |
| `adduce install-skill [--client CLIENT]` | install a supported global agent skill without changing MCP configuration |
| `adduce coverage` | what each language's extractors cover, and what they miss |
| `adduce resolvers` | the declared resolver order |
| `adduce schema` | the published JSON Schema the payloads validate against |
| `adduce health` | whether the engine is degraded |

**Watch an estate change over time** — each takes artifacts, oldest first

| Command | Answers |
|---|---|
| `adduce diff <before> <after>` | what changed in the graph between two artifacts |
| `adduce history <artifact>...` | when each edge existed across a series |
| `adduce pr --base ... --head ...` | which consumers a branch breaks, with a citation for each |
| `adduce drift <head>... --base <base>...` | operations a provider dropped that consumers still call |
| `adduce deprecations <artifact>...` | deprecated contracts that still have live consumers |

**Keep it honest**

| Command | Answers |
|---|---|
| `adduce reverify <artifact> --repo-root DIR` | does the cited line still say that? Stale evidence downgrades confidence, never deletes |
| `adduce suggest-aliases <artifact>...` | draft `service_aliases.yml` entries from unmatched hints — prints only, never applies |
| `adduce reviews` | operator review decisions as labelled true/false-positive data |

`suggest-aliases` and `reverify` are deliberately advisory: an alias is an
operator's assertion of identity, and rot ages an assertion rather than
refuting it. Neither ever writes.

## Model Context Protocol (MCP)

Adduce serves source repositories or portable artifacts to AI clients over
MCP stdio. It completes the MCP handshake immediately, then scans or loads
every input once on the first graph query and answers subsequent calls from
the linked in-memory graph.

### Automatic indexing

On the first graph query, `adduce mcp` scans each input directory once.
Subsequent queries answer from the in-memory graph with no re-scan. To pick up
source changes, restart the MCP server or create fresh artifacts.

### Multi-repository workspaces

Pass every repository as its own argument:

```bash
adduce mcp /path/to/order-service /path/to/billing-service /path/to/gateway
```

Adduce parses all inputs, links their claims, and answers cross-repository
questions from the unified graph — a query from inside `order-service` can
cite callers in `billing-service` and routes in `gateway`.

### Exposed MCP Tools

| MCP Tool | Description | Inputs |
|---|---|---|
| **`services`** | Repository-backed services, plus artifact commit metadata | *(none)* |
| **`consumers_of`** | Active incoming edges with `file:line` evidence | `node_id` |
| **`trace`** | Up to 3 shortest active paths between two node IDs | `from_id`, `to_id`, `max_hops` |
| **`deprecations`** | Deprecated contract endpoints and their live active consumers | *(none)* |

MCP client configuration is deliberately not rewritten by the installer.
See [Agent and MCP integration](docs/plugins-and-mcp-guide.md) for the
client-specific commands, supported global skill paths, and input semantics.

## Accuracy, and how to check it yourself

Claims about accuracy are worth nothing unless you can reproduce them, so the
harness is in the repo and runs against whatever you have ingested:

```bash
python scripts/accuracy/verify_edges.py    # precision: does the cited source support the edge?
python scripts/accuracy/measure_recall.py  # recall: is every fact in the source in the graph?
```

`verify_edges.py` re-reads the file and line each edge cites and judges whether
the claim holds there — it never asks the graph to confirm itself.
`measure_recall.py` goes the other way, enumerating ground truth from the
source and looking for it in the graph.

A representative run over the demo corpus. Precision is **sampled** per
stratum, so the exact counts move between runs; "weak" means the source
supports the edge but the checker could not match the path literally:

| Edge stratum | TP | Weak | FP |
|---|---|---|---|
| `CALLS_SERVICE` / compose `depends_on` | 49 | 0 | 0 |
| `CALLS_SERVICE` / compose env host | 15 | 0 | 0 |
| `EXPOSES` / route annotation | 53 | 11 | 0 |
| `EXPOSES` / MCP tool contract | 25 | 0 | 0 |
| `INVOKES` / config-derived host | 7 | 0 | 0 |
| `INVOKES` / gateway-rewritten path | 17 | 0 | 0 |
| `READS_FROM` / `WRITES_TO` / SQL | 15 | 0 | 0 |

Recall is exhaustive for the categories it enumerates — compose `depends_on`
11/11, 13/13 and 10/10 on the three compose repos, gateway routes 4/4.

Treat a clean sheet with suspicion rather than pride: it partly reflects which
categories have a ground-truth enumerator at all. Messaging, package
dependencies, gRPC and GraphQL still have none, and a category nobody
enumerates contributes nothing to these numbers while looking like success.
**If you add a resolver, add an enumerator with it** — writing the
gateway-route enumerator immediately found two defects neither the unit tests
nor the precision pass could see, one of which had manufactured 1,057 endpoint
contracts that do not exist.

One caveat the harness prints for you: it measures the **stored** graph, which
was written by whatever version of the extractors ran at ingest time. A repo
ingested before a fix will still show that fix's bug, so re-ingest before
believing a low score.

## Architecture

```
GitHub repo ──▶ parsers ──▶ claims ──▶ linker (R0–R14) ──▶ typed edges ──▶ store
                (tree-sitter,          rendezvous on
                 compose, k8s,         shared keys
                 Helm, proto,
                 OpenAPI, …)
```

- **Backend** — Python 3.14, FastAPI, Neo4j 5.26 (or SQLite, or in-memory). Tree-sitter AST parsing for 19
  languages (Java, Kotlin, Python, JavaScript, TypeScript, Go, Rust, C, C++,
  C#, Ruby, PHP, Scala, R, SQL, JSON, YAML, HTML, CSS), plus purpose-built
  parsers for compose, Kubernetes, Helm, Kustomize, Terraform, protobuf,
  GraphQL SDL, OpenAPI, AsyncAPI, C# ASP.NET Core Minimal APIs, and MCP
  capability manifests. Several languages carry extra extraction queries on
  top of the AST layer.
- **Frontend** — React 19 + Vite + Tailwind + zustand, canvas graph rendering.
- **Linking** — ingestion and linking are separate phases. Ingesting a repo
  never rewrites another repo's nodes; `POST /api/v2/links/rebuild` reconciles.

| Path | Contents |
|---|---|
| `backend/adduce/parsers/` | language and manifest parsers |
| `backend/adduce/services/claims.py` | the claim registry — start here |
| `backend/adduce/services/linker/` | resolvers R0–R14, fusion, rollups |
| `config/confidence.yml` | versioned confidence table |
| `scripts/accuracy/` | the precision and recall harness |
| `backend/tools/check_*.py` | the four static gates a change must pass |
| `packaging/adduce-core/` | the library distribution |
| `docs/` | usage and design documents |

## Configuration

Everything is set in `.env`, generated by `./scripts/setup.sh`. The values
worth knowing:

| Variable | Default | Meaning |
|---|---|---|
| `BIND_ADDR` | `127.0.0.1` | interface the ports bind to |
| `AUTH_ENABLED` | `false` | token required on every route when true |
| `MAX_SCOPE_REPOS` | `10` | repositories selectable at once in the UI |
| `GRAPH_DETAIL_NODE_LIMIT` | `80` | exact nodes shown in bounded Module, Focus and Impact canvases |
| `GITHUB_TOKEN` | *(empty)* | needed only for private repositories |

**Security posture.** Ports bind to `127.0.0.1` and authentication is off,
including for writes. That is deliberate for a local single-user stack and
safe only because nothing off your machine can reach it. If you change
`BIND_ADDR`, set `AUTH_ENABLED=true` and `API_TOKEN` in the same edit. Config
values are HMAC-redacted at parse time, so secrets found in ingested repos
never reach nodes, claims, or evidence.

## Documentation

| Document | Covers |
|---|---|
| [Developer use cases](docs/use-cases.md) | valid CLI, artifact, CI, MCP, and embedding examples |
| [Agent and MCP integration](docs/plugins-and-mcp-guide.md) | client registration, skill installation, and MCP input semantics |
| [Using the views](docs/using-the-views.md) | the three views and their shared controls |
| [Frontend UX implementation and QA](docs/future/navigation-and-feature-qa-2026-08-30.md) | current navigation contract, browser matrix and redesign status |
| [Agent plugin](plugins/adduce/) | one validated plugin source for Claude Code, Codex, and Kimi Code |
| [Coverage gaps](docs/design/coverage-gaps.md) | what the graph still misses, ranked, with reproducible measurements |
| [Comparison](docs/comparison.md) | against code-graph tools, catalogs and runtime maps, with measured numbers |
| [CONTRIBUTING](CONTRIBUTING.md) | setup, the one rule that matters, adding a parser or resolver |


## Contributing

The most valuable contributions are **new resolvers and parsers** — every
ecosystem joins services differently, and the ones covered so far reflect the
systems the authors had to hand. If this misses your stack, that gap is the
contribution. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE).
