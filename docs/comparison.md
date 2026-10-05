# How TraceKite fits with other tools

[Docs](README.md) · [Use cases](use-cases.md)

TraceKite is useful when a connection is spread across source repositories:
a frontend builds a URL, deployment config supplies its host, and a backend
registers the route. It joins supported static evidence and cites the source.

## Choose by question

| Question | Primary evidence | Where TraceKite fits |
|---|---|---|
| Which symbol references this method? | Compiler/language indexes and import analysis | Local call extraction and SCIP input provide some context; compiler tooling remains useful |
| Who owns or operates this service? | Service catalog and team-maintained metadata | Reads supported CODEOWNERS/catalog evidence; does not replace on-call/lifecycle management |
| What called this service in production? | Runtime traces, logs, metrics | Does not capture traffic or latency |
| Which indexed consumers could this API or package change affect? | Source, configuration, contracts, and before/after snapshots | Core use case: establish connections, citations, and supported dependency losses |
| Is this change safe to deploy? | Tests, runtime behavior, policy, and review | Supplies evidence for the decision; cannot make the decision alone |

## Use the evidence together

Static analysis can find a supported relationship before deployment, including
paths that may not appear in a captured traffic window. Runtime tools can reveal
dynamic behavior that has no recoverable static key. Catalogs add operational
intent and ownership that source may not contain.

TraceKite indexes source nodes as well as contracts; it is inaccurate to say it
has no symbol graph. It is equally inaccurate to describe it as complete
compiler-level call resolution. See [features](features.md) and
[coverage limits](design/coverage-gaps.md) for the actual boundary.

A stored graph can become stale when code changes. Refresh/rebuild the relevant
surface, verify source revisions, and read coverage and truncation before
using a negative result. Confidence in one edge does not make the whole graph
complete.

## Portability

The Python library, CLI, and MCP work without the web application. Artifacts
use SQLite; the Docker app uses Neo4j. Both use the same extraction/linking
engine, with different queries and storage paths. There is no shipped DuckDB
backend or automatic switch of the app to SQLite.

For commands and implementation boundaries, see [library integration](library.md)
and [architecture](design/architecture.md). Historical benchmark figures are
kept in [scale measurements](future/scale-measurements.md), not used as universal
accuracy or performance claims.
