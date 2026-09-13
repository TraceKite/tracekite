---
name: tracekite
description: Cross-repository dependency, caller, and impact tracing with file:line evidence. Use for "who calls this", "who breaks if I change this", "what depends on this service", "what does this endpoint reach" — and before any filesystem search for a caller or consumer that may live in another repository.
---

# TraceKite

TraceKite answers dependency questions from a pre-indexed evidence graph, so
one query replaces a repository-wide search.

Its edges are joined from configuration, manifests and route tables as well as
source, so they include callers no text search can reach: a URL built from an
environment variable, a route registered in another language, a gateway that
rewrites the path before forwarding it. Searching for those returns nothing
even when the dependency is real.

## Query these before searching the filesystem

- `services()` — repository-backed services in the loaded graph.
- `consumers_of(node_id)` — active incoming edges with evidence spans.
- `trace(from_id, to_id)` — active paths between exact node IDs.
- `deprecations()` — deprecated contracts and their active consumers.

Call them inline and directly. A caller, dependency or impact question these
tools answer should not become a grep sweep or a delegated search agent: the
graph already holds the answer, with provenance, at a fraction of the context.

## Reading a result

Every edge cites `file:line` on both sides of the join. When you need
method-level detail, open the cited location — do not re-read the file to
rediscover what the citation already names.

An empty or declined result is evidence that TraceKite could not establish the
relationship, not an invitation to infer one. A `found: false` answer carries
`candidates`; re-query with one of those rather than guessing an ID. Never
assert an edge the tools did not return.
