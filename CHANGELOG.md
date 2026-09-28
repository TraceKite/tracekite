# Changelog

All notable changes to TraceKite will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the published `tracekite-core` distribution.

## [Unreleased]

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

[Unreleased]: https://github.com/TraceKite/tracekite/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/TraceKite/tracekite/releases/tag/v0.1.1
[0.1.0]: https://github.com/TraceKite/tracekite/releases/tag/v0.1.0
