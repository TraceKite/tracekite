# Goal

TraceKite establishes **what is connected across repositories, and how we know** —
and nothing beyond that. Incident triage, chat, ranking and retrieval belong to
whatever consumes it.

Its edges are not present in any source file. A call site holds
`f"{self._registry_url}/v1/callers"`; the route lives in another repo's Go
handler; the host arrives from a compose env var. No AST reaches across that
gap. So TraceKite emits **claims** from each artifact independently, then joins
them on a shared rendezvous key — making the join evidence rather than
inference, with a file and line cited on *both* sides of every edge.

## Where it stands

The repository contains an embeddable scan/link engine, portable artifacts,
incremental scan reuse, a CLI, an integration facade and MCP tools, alongside
the FastAPI + Neo4j + React application. `GraphStore` and its SQLite, Neo4j and
in-memory implementations exist. The narrower `LinkerStore` remains active for
link runs. Source packaging lives in `packaging/tracekite-core`; distribution
availability and installed-wheel validation are separate release checks.

`tracekite pr` already compares base/head artifacts and reports indexed consumer
losses; `drift` and `reverify` also exist. These are not yet a complete stored
receipt replay and agent-claim verification protocol. A lost indexed connection
does not by itself prove a runtime failure, and exit zero is not deletion
permission. See [agent verification](agent-verification-layer.md).

The six-repository figures (38,696 nodes, 62,854 edges and 189 TP / 0 FP) are
historical reference measurements, not current inventory or universal accuracy.
Architecture §7.5 records later synthetic runs at 100 and 1,001 repositories,
including limitations of their claim density. It is no longer accurate to
describe all scale evidence as extrapolation; production-scale qualification
still needs representative workloads.

## The goal

Maintain one engine that a host embeds, governed by
`docs/design/architecture.md`, which is normative, and qualify its integrations
against reproducible source, scope and release evidence.

TraceKite has **two surfaces over one engine**:

- the Docker Compose application;
- the `tracekite-core` library/CLI distribution: the host supplies storage or
  none, without adopting the application server.

On pull requests, report **which indexed consumers lose supported connections**,
with source evidence and limitations. Extend this to recheckable structural
claims across large estates without claiming exhaustive runtime safety.

## Historical phase gates and current qualification

These are acceptance areas from the original roadmap, not assertions that every
component remains unbuilt or every phase is complete. Implementation, installed
package validation, representative accuracy and release qualification are
different proof layers; the active tracker and release evidence determine status.

1. **Embeddable** (17) — package split, pure `scan()`/`link()`, GraphStore
   protocol over SQLite/Neo4j/in-memory, determinism, CLI.
   *Exit: a host scans two repos and never imports FastAPI or Neo4j.*
2. **Scale** (27) — portable per-repo artifacts, incremental re-ingest,
   parallel map/reduce, skew guard, observability, CI precision gate.
   *Exit: a synthetic 1,000-repo estate links within budget; one push re-links
   in seconds, not 81 minutes.*
3. **Model** (10) — UI_CALLS, vendor catalog, SCIP import for symbol calls,
   `tracekite explain`. *Exit: every edge explains its own derivation.*
4. **Change** (21) — temporal, PR mode, contract drift, calibrated confidence.
   *Exit: a PR report names supported indexed losses with citations and explicit
   scope; its runtime implications and missing evidence are not overstated.*
5. **Breadth** (14) — protocol and IaC long tail, MCP surface, fixtures.

## Non-negotiable

- **Precision is the product.** Regressions against the labeled precision gate
  are defects. The historical 189 TP / 0 FP result applies to its measured
  cases, not every graph or future input. Decline-don't-guess stays: a decline
  is recorded data, never silence.
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

## Shared verification and context direction

Build one shared evidence/receipt foundation. The first new delivery is a scoped
agent-claim verifier using the existing PR analysis. The optional Evidence
Compiler consumes that foundation to select and maintain task context under a
budget. A verifier can ship without a compiler; the compiler must not create a
second graph, receipt identity or semantic validator.

The [verification design](agent-verification-layer.md) owns the proposed shared
contract and verification policy boundary. The [compiler strategy](../future/evidence-compiler-strategy.md)
owns the optional context-selection experiment and its economic tests. Neither
document changes the core prohibition on general agent planning or authorizes
edits, deletion, merging or deployment from graph evidence alone.
