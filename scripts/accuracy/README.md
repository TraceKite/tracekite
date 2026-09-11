# Measuring the graph against real repositories

The calibration harness in `backend/tracekite/services/calibration.py` scores the
resolvers on hand-built labelled estates. It is necessary but not sufficient:
it can only be as good as the cases someone thought to write, and a tier with
no estate scores nothing at all while still reporting 1.0 overall.

These two scripts measure the graph against repositories that are actually
ingested. Neither asks the graph whether it agrees with itself.

Both take repo ids as arguments and default to every repo in the graph:

    python scripts/accuracy/verify_edges.py
    python scripts/accuracy/measure_recall.py spring-petclinic_spring-petclinic-cloud

Shared plumbing lives in `_kg.py`. Container names, the Neo4j credentials and
the workspace root all come from the environment (`KG_NEO4J_CONTAINER`,
`KG_BACKEND_CONTAINER`, `NEO4J_PASSWORD`, `KG_REPO_ROOT`), so nothing is
pinned to one machine or one estate.

## `verify_edges.py` — precision

Samples edges per stratum, reads the `file:line` each cites as evidence out of
the ingested clone, and decides whether the source supports the claim.

Verdicts: `TP` supported, `TP_WEAK` partially supported, `FP?` not supported,
`UNVERIFIABLE` no mechanical check possible.

**Every `FP?` must be read by hand before being believed — the checker has been
wrong at least as often as the graph.** Three times so far:

- A Next.js `export const GET = withGuards(...)` handler was flagged because
  the regex only recognised `export function GET`. The graph was right.
- `s.HandlePath(http.MethodGet, ...)` in grpc-gateway was flagged because the
  pattern matched `Handle(` and `HandlePath` never reached the paren. Ordered
  alternation, correctly ordered, fixed it. The graph was right.
- The whole MCP stratum scored 0.00 because the checker read `b.name` on a
  node type whose tool name lives in `b.rpc`. Every row compared against
  `NULL`. The graph was right.

The pattern is consistent enough to be a rule: when a stratum scores
suspiciously badly, suspect the checker first.

## `measure_recall.py` — recall

The opposite direction, and exhaustive rather than sampled for the categories
it covers: enumerates facts from the source — every compose `depends_on`, every
Next.js route handler, every MCP capability manifest — and checks the graph
contains each one. Anything absent is a false negative.

Two things it deliberately does not treat as misses:

- **Cross-repo attribution.** When two repos declare the same dependency
  between the same two services, unification produces one edge stamped with
  whichever repo linked first. The fact is in the graph; requiring this repo's
  id would report a false miss. Such matches are counted and reported
  separately rather than hidden.
- **Nothing to find.** A repo with no compose files scores 0/0, not 0%.

## The trap that matters most: staleness

**These scripts read the stored graph, not your working tree.** The graph was
written by whatever version of the extractors ran at ingest time, so a repo
ingested before a fix will still exhibit that fix's bug.

This is not hypothetical. Compose recall on `spring-petclinic-cloud` read
2/11 and looked like a serious resolver defect. The parser on disk handled all
11 correctly; the repo had simply been ingested before a claim-identity fix
landed. Re-ingesting took the same measurement to 11/11.

Both scripts now print each repo's ingest timestamp for exactly this reason.
Re-ingest before believing a low score.

## What this does not measure

Only the strata listed above. Messaging, package dependencies and gateway
routes have no ground-truth enumerator yet. A category with no enumerator
contributes nothing to these numbers — the same trap as an uncovered
calibration tier, so add an enumerator when you add a resolver.

Note also what the clone contains rather than what your working copy does.
Ingestion does not fetch git submodules, so nothing inside one can appear in
either the source enumeration or the graph. Counts taken from a working copy
with submodules initialised will disagree with these; the clone is the source
of truth for anything the graph is expected to see.
