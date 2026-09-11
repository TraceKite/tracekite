# TraceKite compared, including where it loses

A project that only names its wins is easy to dismiss. This page states what
TraceKite answers that other tools cannot, and — with the same specificity — what
they answer that it cannot.

Every number here is measured on the corpus in this repository: six real
repositories, 39,619 nodes, 62,854 edges, 141 service connections, 189 true
positives and 0 false positives across seven strata.

---

## The distinction that matters

TraceKite's edges are **not lexically present in any source file**. Here is a real
call and the endpoint that serves it:

```python
# projects/foyer/.../registry_projection_cache.py:75          (Python)
callers_resp = await self._http.get(f"{self._registry_url}/v1/callers")
```
```go
// projects/capability-registry/internal/registry/routes.go:34  (Go)
mux.HandleFunc("GET /v1/callers", s.handleCallers)
```

No symbol in the first file names the second service. `_registry_url` is a
constructor parameter injected from configuration. The strongest edge any AST
tool can draw terminates at `httpx.AsyncClient.get` — the HTTP library, which
is exactly where the interesting part begins. And no single AST spans Python
and Go.

**Measured: of the 141 service-level connections in the graph, none could be
derived from source code alone.** Every one required evidence from outside it —
a compose file, a Kubernetes manifest, a gateway route table, or an environment
binding. That is not a tuning difference; it is a different kind of graph.

---

## Against code-graph tools

dependency-cruiser, madge, jdeps, pydeps, code2flow, SCIP/LSIF indexes,
AST-to-Neo4j importers.

| | They graph | TraceKite graphs |
|---|---|---|
| Edge exists because | one symbol names another | two artifacts agree on a rendezvous key |
| Crosses a process boundary | no | yes, that is the point |
| Crosses a language | no | yes — Python call site, Go route |
| Evidence | the reference itself | `file:line` on **both** sides |

**Where they win:** "who calls this function" is their question and they answer
it better. TraceKite works at contract altitude — service, endpoint, topic, table
— and deliberately does not index symbols. If you want to rename a method
safely, use Sourcegraph.

---

## Against service catalogs

Backstage, Cortex, OpsLevel.

**Where they win, and it is not close:** ownership, lifecycle, on-call
rotation, tiering, documentation links. None of that is in the code, and
TraceKite infers ownership only where CODEOWNERS or a catalog file already says
so. A catalog is also a place for humans to record intent, which a derived
graph structurally cannot be.

**Where TraceKite wins:** a catalog is a statement of intent, and it drifts the
first time someone ships without updating it. TraceKite derives from what is
actually in the repositories, so it cannot drift from the code — only from
reality, and only where extraction is incomplete.

---

## Against runtime service maps

Datadog, Kiali, Jaeger, eBPF-based maps.

**Where they win, and this is the real gap:**

- Reflection, dynamic dispatch, and anything assembled at runtime are invisible
  to static extraction.
- **Measured: on one estate, static extraction found 56 of 68 outbound HTTP
  call sites.** Twelve were built in ways no parser recovers.
- A runtime map sees what actually happened, including paths nobody predicted.

**Where TraceKite wins:** a runtime map shows what *did* happen in an observed
window, not what *can*. A path not exercised is invisible, and none of it
exists before you deploy. TraceKite answers "if I change this endpoint, who
breaks?" from a git clone, before anything runs.

**Use both if you have both.** They fail in opposite directions, and the
overlap is where you should be most confident.

---

## Where TraceKite loses outright

Stated plainly, because a tool that hides these is worse than one that names
them.

1. **Dynamic call construction.** 12 of 68 call sites on the measured estate.
   A URL assembled from a database value or a runtime registry lookup has no
   static evidence, and TraceKite declines rather than guessing.
2. **Symbol-level resolution.** Not attempted. `tracekite` cannot tell you which
   function calls which; that is a different altitude and a different index.
3. **Ownership and lifecycle** beyond what CODEOWNERS or a catalog states.
4. **Anything requiring the code to run.** Feature flags evaluated at runtime,
   config fetched from a service, dependency injection resolved by a
   container at startup.
5. **Recall is not the product.** Precision is. TraceKite declines an ambiguous
   signal and records the decline; a tool optimising for coverage would emit
   the likeliest answer. If you need every possible edge and can tolerate
   wrong ones, this is the wrong tool.

---

## What is deliberately not locked in

Measured against the codebase, because portability claims are cheap:

- **Zero APOC, zero GDS, zero full-text, zero vector.** Portable Cypher only.
- **`shortestPath` is never used** — the one traversal with no recursive-CTE
  equivalent. That is why the same test suite passes against SQLite, Neo4j and
  in-memory backends.
- Exactly **four** variable-length queries, all bounded (`*1..n`, `max_hops ≤
  8`) with edge-type predicates.

An estate can move to SQLite without re-ingesting: `migrate_to_sqlite()`
copied 39,619 nodes and 62,854 edges in 6.5s, preserving all 141 service
connections.

---

## The honest summary

TraceKite is for the window between writing code and running it in production,
and for the question a catalog can only answer if somebody remembered to
update it. It is **static, derived rather than declared, and at contract
altitude rather than symbol altitude.**

If your question is "who calls this function", use a code intelligence tool.
If it is "who owns this service", use a catalog. If it is "what actually
talked to what last Tuesday", use a runtime map.

If it is **"if I change this endpoint, who breaks — and how do I check that
you're right"**, that is the one this answers, with a file and line on both
sides of every edge.
