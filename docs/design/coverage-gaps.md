# Coverage limits and known gaps

[Docs](../README.md) · [Features](../features.md) · [Reading answers](../answers.md)

This page describes implementation limits in 0.2.0. A missing edge is not proof
that no connection exists. Use scan coverage and resolver decline counters to
understand the missing evidence in your own repositories.

## Extraction and identity

| Limit | What to do |
|---|---|
| Dynamic hosts, paths, reflection, or custom wrappers | Supply static config where it exists; inspect unresolved counters and runtime evidence separately |
| Ambiguous service ownership in monorepos | Inspect Compose build contexts/application names and explicit aliases; avoid merging generic names by guesswork |
| Flask blueprint registration across files | Same-file literal registrations are supported; cross-file/dynamic prefixes can be declined |
| Imports are parsed but not emitted as edges | Use compiler/import tooling for an exhaustive import graph |
| Local calls are heuristic unless SCIP evidence is supplied | Validate symbol-level conclusions with language tooling |
| Unfetched Git submodules | Server clone does not recurse; scans/artifacts report missing submodules rather than including their contents |
| External services | Vendor catalog classifies supported unmatched hosts; it does not create a complete external-service graph |
| Parser coverage differs from framework extraction | Inspect actual scan failures/skips and `tracekite coverage`; its 0.2.0 HTTP matrix omits the implemented JS file-based route families |

## Interface differences

- Repo is a bounded source-code view; Service Map needs service identities and a
  completed link run. Different totals are expected.
- Repo Impact is two outgoing local hops. HTTP repo impact is library-only.
  MCP/Python impact follows transitive dependency edges backwards.
- Repo **Show connections only** filters using `INVOKES`/`EXPOSES`; it can hide
  source nodes connected only by `UI_CALLS`. Keep the filter off for those calls.
- MCP/Python node/search can resolve local source identities, but their
  traversals use linker edges, not every local `CALLS`/`CONTAINS` edge.
- Python 0.2.0 `services()` and `deprecations()` may return `present` with empty
  collections. MCP uses `known_empty`; check the result collection too.
- Query truncation and scan completeness are separate fields. Always read both.
- No-invocation candidates in the HTTP deprecated endpoint check `INVOKES` only;
  inspect frontend `UI_CALLS` and coverage before treating them as unused.

## Refresh, persistence, and scale

- Successful ingests automatically relink, but remote Git changes do not trigger
  ingestion. MCP/facade snapshots load once and need an explicit restart/reload.
- Docker ingestion parses serially within each repo. Parallel/file-sharded scan
  APIs exist separately; raising `INGEST_WORKERS` only runs more repo jobs.
- Artifact reuse compares source content only. Use fresh output directories
  after engine/configuration/redaction-key or revision-metadata changes.
- Compaction upserts records; it is not a replacement snapshot or a link run.
  Use one revision per repo and a fresh compacted database.
- Neo4j link runs use multiple transactions. Interrupted runs can leave a partial
  cache; inspect the failed job and complete a new run.
- CLI ingest cannot send TraceKite API bearer headers in 0.2.0. Use an HTTP client
  for authenticated servers. Its `--token` is for the Git host.

## What the accuracy harness establishes

The [harness](../../scripts/accuracy/README.md) samples source-backed precision and
enumerates recall for Compose dependencies, supported Next.js handlers, gateway
routes, and MCP capability manifests. It does not exhaustively enumerate message,
package, gRPC, GraphQL, or dynamic runtime dependencies.

Re-ingest before measuring extraction changes. A score applies to the stored
revision, categories, and samples tested, not to all code the tool could see.
Report missing patterns with a small reproducible fixture and expected evidence;
see [CONTRIBUTING](../../CONTRIBUTING.md).
