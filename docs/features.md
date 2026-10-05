# Features and coverage

[Docs](README.md) · [Use cases](use-cases.md) · [Known limits](design/coverage-gaps.md)

TraceKite combines source-code structure with connections inferred from supported
code and configuration patterns. These are static findings, backed by citations.

## Pick the right interface

| Capability | Browser app | CLI | Python / MCP |
|---|---|---|---|
| Inspect source structure and node properties | Repo: 2D/3D, search, drawers | `scan`, `artifact` | `search`, `node`; lower-level Python scan |
| See services and their connections | Service Map | `link` JSON | `services`, `neighbors`, `subgraph` |
| Follow a path | Trace with Service/Code altitude | Link/explain data | `trace` over linker edges |
| Inspect direct consumers | Service Map relationship drawer | Link data | `consumers_of` |
| Inspect transitive dependents | Repo Impact is a different, local outgoing view | `pr` compares snapshots | `impact` traverses dependency edges backwards |
| Compare snapshots | No dedicated UI | `diff`, `history`, `pr`, `drift` | Lower-level Python modules |
| Check stale citations and deprecations | Evidence drawer; more via HTTP API | `reverify`, `deprecations` | `deprecations` |
| Load code into Neo4j | Ingest, Refresh, Delete | `ingest` | HTTP API, not MCP |
| Inspect libraries, topics, env ownership, reviews | [HTTP API](api.md); no dedicated tabs | Some via link/review reports | Graph methods where a linker edge exists |
| Save portable snapshots | No artifact download button | `artifact` | SQLite artifact and store APIs |

The standalone tools do not read the Docker app's database. Point them at the
same source revisions or artifacts when comparing results.

## Connections the engine can establish

| Evidence family | Examples of supported inputs | Graph result |
|---|---|---|
| Service identity | Compose build contexts, application names, Kubernetes descriptors, configured aliases | Services, aliases, modules, deployments |
| Deployment topology | Compose dependencies/env hosts, Kubernetes selectors/DNS, supported mesh policy | Service calls, deployment bindings, permitted traffic |
| HTTP and UI calls | Literal/template calls, route handlers, OpenAPI, supported gateway rewrites | HTTP contracts, providers, callers, UI calls |
| gRPC and GraphQL | Protobuf/services/stubs, GraphQL declarations and operations | Operation contracts and matching code sites |
| Messaging | Publish/consume patterns, AsyncAPI, supported Terraform queues/topics and Avro | Topics, publishers, consumers, fan-out |
| Libraries | Package manifests, lockfiles, and publish identities | Internal publishers, consumers, versions |
| Data | Supported SQL/ORM queries, migrations, data pipeline declarations | Dataset declarations, reads, writes |
| Agents and ownership | MCP manifests/code/config, agent cards, CODEOWNERS/catalogs | Operation contracts, callers, ownership |
| Cross-protocol relationships | Supported webhooks and operation bindings | Webhook registration and same-operation links |

Resolvers decline ambiguous joins and count the reason. A service name or URL
fragment by itself is not enough to invent a cross-repository connection.
`tracekite resolvers` prints the registered resolver phases and order.

## Languages and framework coverage

Run `tracekite coverage` for the declared HTTP route/client matrix. In 0.2.0 it
lists 13 languages; 11 have at least one route and client pattern, while C/C++
HTTP patterns are explicitly declined. This is not the parser-language count
or a promise of complete support for every framework in those languages.

Examples include JS/TS Express, Koa, Fastify and NestJS; Java/Kotlin Spring;
Python FastAPI/Flask; Go net/http, Gin, chi and related routers; Rust Axum/Actix/
Rocket; and supported C#, Ruby and PHP patterns. JS/TS also has file-based
Next.js and Remix/React Router extraction. The 0.2.0 `coverage` matrix does not
list those file-based route families; their behavior is pinned by
[JS route tests](../backend/tests/test_js_route_extractor.py).

A React/Vue/TypeScript file can contribute code nodes or HTTP callers without
creating a service identity. Dynamic URL construction and custom wrappers may
remain unresolved. Optional HTML/CSS grammars are available with
`tracekite-core[languages]`; inspect the scan's actual coverage.

## What is deliberately not promised

- Observed production traffic, latency, uptime, or runtime execution paths.
- Complete language/compiler-level symbol resolution or emitted import edges.
- Automatic discovery of every repository in an organization or Git push watching.
- That an empty graph result proves a safe change.
- That every feature appears as a browser tab or MCP tool.

See [coverage limits](design/coverage-gaps.md) and [reading answers](answers.md)
before making a change decision. Use the [accuracy harness](../scripts/accuracy/README.md)
to measure your own stored graph; published QA counts describe only the tested
inputs and categories.
