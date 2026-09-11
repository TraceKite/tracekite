# Goal

Evigraph establishes **what is connected across repositories, and how we know** —
and nothing beyond that. Incident triage, chat, ranking and retrieval belong to
whatever consumes it.

Its edges are not present in any source file. A call site holds
`f"{self._registry_url}/v1/callers"`; the route lives in another repo's Go
handler; the host arrives from a compose env var. No AST reaches across that
gap. So Evigraph emits **claims** from each artifact independently, then joins
them on a shared rendezvous key — making the join evidence rather than
inference, with a file and line cited on *both* sides of every edge.

## Where it stands

Working today on six real repositories: 16 resolvers, 19 claim kinds, 19
tree-sitter languages, 21 config/IaC parsers. 38,696 nodes, 62,854 edges, 141
service connections, **189 true positives and 0 false positives** across seven
strata. A full link takes ~10 seconds.

It is currently an application: FastAPI + Neo4j + React on Docker Compose.

## The goal

Become an engine that a host embeds, governed by
`docs/design/architecture.md`, which is normative.

At the end Evigraph is **two surfaces over one engine**:

- `docker compose up` — the product, exactly as today
- `pip install evigraph-core` — the same engine as a library: no server, no
  database, host supplies storage or none

…and it answers, on every pull request, **which consumers a change breaks**,
with a file and line for each, across an estate of a thousand repositories.

## Phase gates

1. **Embeddable** (17) — package split, pure `scan()`/`link()`, GraphStore
   protocol over SQLite/Neo4j/in-memory, determinism, CLI.
   *Exit: a host scans two repos and never imports FastAPI or Neo4j.*
2. **Scale** (27) — portable per-repo artifacts, incremental re-ingest,
   parallel map/reduce, skew guard, observability, CI precision gate.
   *Exit: a synthetic 1,000-repo estate links within budget; one push re-links
   in seconds, not 81 minutes.*
3. **Model** (10) — UI_CALLS, vendor catalog, SCIP import for symbol calls,
   `evigraph explain`. *Exit: every edge explains its own derivation.*
4. **Change** (21) — temporal, PR mode, contract drift, calibrated confidence.
   *Exit: a PR comment names exactly who breaks.*
5. **Breadth** (14) — protocol and IaC long tail, MCP surface, fixtures.

## Non-negotiable

- **Precision is the product.** 189 TP / 0 FP survives every change, or the
  change is wrong. Decline-don't-guess stays: a decline is recorded data, never
  silence.
- **Ten invariants hold** (architecture §6). Two are load-bearing. **I8** —
  side tables stay O(services + rules), never O(claims); the moment one goes
  claim-proportional the estate stops sharding. **I9** — rendezvous keys are
  final before the join; a key rewritten after partitioning loses its edge
  silently.
- **Determinism is not tidiness.** Identical inputs must yield byte-identical
  artifacts, or PR mode, caching, diffing and CI gates are all unbuildable.
- **The server may orchestrate; it may not compute.** Anything that computes a
  fact about the graph lives below the store layer, or library users silently
  get a worse graph than app users.
- **No duplicate code.** One implementation, both surfaces.

## What to expect

Phases 1 and 2 are 44 of 89 tasks and add **zero visible features** — the
screen looks identical when they land. Everything bought is optionality: the
ability to do Phases 3–4 at all, and to be depended on rather than
reimplemented.

The riskiest single task is B2, the SQLite backend: it sits on the critical
path and is a from-scratch port of all CRUD plus four recursive CTEs. The
1,000-repo figures are extrapolated from six real ones, so H8 probes that at
100 repos early, before the parallel work is designed on top of it.
