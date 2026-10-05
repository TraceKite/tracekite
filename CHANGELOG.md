# Changelog

All notable changes to TraceKite will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the published `tracekite-core` distribution.

## [Unreleased]

### Fixed

- Link jobs report resolution, write, cleanup, and finalization progress during
  long Neo4j rebuilds instead of remaining at 10 percent until completion.
- Multi-repository code views retain `UI_CALLS` edges and their frontend call
  evidence instead of showing the frontend and backend as disconnected.
- Protobuf, Terraform, Avro, and other dedicated structured-file parsers count
  as parsed coverage, so MCP completeness no longer calls extracted evidence
  unsupported.
- Migration ownership claims cite the statement that names each table across
  SQL, Prisma, Flyway, Alembic, Django, Liquibase, Rails, and EF migrations.
- Neo4j cleanup queries use scoped subqueries accepted without deprecation
  warnings by Neo4j 5.26 and later.
- The real-repository recall harness enumerates only files admitted by the
  stored scan and excludes test Compose files from production recall.

## [0.2.0] - 2026-10-04

### Added

- MCP node identity and ranked search, bounded neighbors and subgraphs, and
  transitive impact paths with evidence, confidence bounds, deterministic
  budgets, and explicit truncation.
- Flask application and same-file blueprint route extraction, including
  literal method lists, registration overrides, nested prefixes, and visible
  declines for dynamic or cross-file-unresolved mounts.
- File-precise monorepo attribution for `tracekite pr --changed-file`.

### Changed

- The UI repository-scope default is 20, and node and edge filters list the
  types actually returned by the selected view with live counts.
- MCP consumer and trace edges expose resolver, match, repository, confidence,
  rendezvous, and evidence-span metadata already carried by the graph.
- Re-ingesting a known repository replaces its graph so deleted source cannot
  keep stale claims or edges alive.

### Fixed

- Workspace `packages/` directories are scanned as first-party code; NuGet
  restore folders remain excluded. Scoped npm and Go publishers now join the
  same package keys as their consumers, while private packages publish no
  public library identity.
- Route extraction no longer invents Go 1.22, Express, chi, Fastify, Echo, or
  Fiber endpoints; preserves `ANY`; keeps every Rust chain registration; and
  distinguishes Express middleware from routes. Next.js App Router paths keep
  an `app` URL segment instead of mistaking it for a second router root.
- Cross-repository gateway link runs use the target's real label and report
  the exact missing row when fail-closed reconciliation rejects a write.
- Graph views return parents for selected nodes, search ranks exact spelling
  and case first, and repository failures remain legible and selectable.
- Drift, evidence re-verification, consumer lookup, and explain output avoid
  the false results found across the large-repository qualification estate.
- Bracketed deployment placeholders in URL-shaped config values decline to an
  opaque redacted value instead of aborting ingestion, and failed ingests no
  longer enqueue a link run.
- UTF-8 BOM-prefixed manifests retain their dependency and publish identities.
- Call-graph caller resolution indexes symbols by file instead of scanning the
  entire repository for every call site, removing the dominant large-monorepo
  ingest cost.
- Restart-reaped jobs normalize Neo4j timestamps before API validation, so
  their status remains inspectable after a backend replacement.
- Full-link submissions remain coalesced while the exclusive linker waits or
  runs, preventing a burst of ingests from scheduling duplicate rebuilds.
- Portable artifact builds use a temporary database on the destination
  filesystem, so atomic publication works across mounted Docker volumes and
  leaves no temporary directory behind.
- Repository-level library dependencies carry consumer citations at consumer
  confidence instead of uncited publisher confidence.
- The lockfile now matches the declared tree-sitter grammar pins, so local,
  container, and release installs test the same parser versions.

## [0.1.1] - 2026-09-28

### Fixed

- Parallel and sharded scans no longer drop files where worker processes are
  started with `fork()`, the default on Linux before Python 3.14. A worker
  forked after its parent had parsed anything inherited a parse pool with no
  threads behind it, so every parse in the worker timed out and was skipped,
  and the parallel artifact differed from the serial one.

## [0.1.0] - 2026-09-19

Tagged but not published to PyPI: its release build failed on the defect
fixed in 0.1.1.

### Added

- Evidence-backed cross-repository scanning and deterministic linking.
- Standalone CLI and embeddable Python facade.
- MCP tools for service discovery, consumers, traces, and deprecations.
- Content-addressed `.tracekite` artifacts.
- Local FastAPI, Neo4j, and web application deployment through Docker Compose.
- Open-source governance, security reporting, support, and contribution
  templates.
- Release checks for clean wheel and source-distribution installs.

[Unreleased]: https://github.com/TraceKite/tracekite/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/TraceKite/tracekite/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/TraceKite/tracekite/releases/tag/v0.1.1
[0.1.0]: https://github.com/TraceKite/tracekite/releases/tag/v0.1.0
