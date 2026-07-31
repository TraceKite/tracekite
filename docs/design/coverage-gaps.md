# Where the graph is still thin

Measured against the public demo corpus, so every number here is reproducible:

```bash
docker compose up -d --build
# ingest spring-petclinic-cloud, spring-petclinic-microservices,
#        kafka-streams-examples, grpc-gateway, then:
curl -X POST http://localhost:28000/api/v2/links/rebuild
python scripts/accuracy/verify_edges.py
python scripts/accuracy/measure_recall.py
```

These are the gaps worth contributing to, ranked. Gap 1 is the one that
matters most and is the best first contribution in the repository.

---

## Gap 1 — the consumer and the provider speak different path spaces — FIXED

> **Resolved.** `_qualify_from_gateway` in `r7_http.py` now consults the
> gateway route table before declaring a call site unqualified. On the
> petclinic corpus this took code-derived `INVOKES` edges from 1 to 24, added
> three code-derived service-level edges (`api-gateway → vets-service`,
> `→ customers-service`, `→ genai-service`), and verified at 17/17 with zero
> false positives. Kept below for the reasoning, which generalises to any
> estate with an API gateway.

Deployment topology extracted well. Code-level calls did not:

| Signal | Before | After |
|---|---|---|
| `CALLS_SERVICE` from compose `depends_on` | 29 | 29 |
| `CALLS_SERVICE` from Kubernetes env hosts | 4 | 4 |
| `CALLS_SERVICE` derived from **code** | **1** | **4** |
| `INVOKES` (contract-level call edges) | **1** | **24** |

24 HTTP consumer claims were extracted and marked matchable, and they produced
one edge. The graph knew your containers referenced each other; it barely knew
your code called anything.

### Why they don't meet

The two halves of a call are written in different path spaces, and the gateway
is the translation nobody applies:

```
consumer claim   httpcall:GET:/api/vet/vets      (the caller goes through the gateway)
route claim      /api/vet → svcname:vets-service (the gateway strips the prefix)
provider claim   GET:/vets                       (the service declares its own path)
```

`/api/vet/vets` and `/vets` never rendezvous, so no edge is emitted — even
though the graph independently holds all three facts, and the `ROUTES_TO` edge
`api-gateway -> vets-service` is already drawn with `application.yml:21` as
evidence.

The single edge that *does* resolve is `GET:/api/gateway/owners/{}`, which
matches only because the gateway declares that path itself.

### How it was fixed

`_qualify_from_gateway` rewrites an unqualified consumer key through every
known gateway route: a route mapping prefix `P` to service `S` lets a consumer
path starting with `P` be retried as `path[len(P):]` against `S`'s providers.

Four properties were load-bearing, and each is worth keeping if you touch it:

- **Ambiguity declines.** Two gateways claiming one prefix for different
  services emits nothing and counts `r7.gateway_prefix_ambiguous`. A wrong
  call edge is worse than a missing one.
- **Local routes win.** Route tables are keyed by gateway *name*, so two repos
  declaring the same gateway share one table. A route the caller's own repo
  declares describes the caller's deployment; another repo's only shares a
  name. Same precedence R7 already applies to providers.
- **Cross-repo evidence names its repo.** When the winning route does come
  from another repo, the edge carries `route_repo`. Without it the evidence
  path resolves against the wrong repo and the UI deep-link 404s — which is
  exactly what the accuracy harness caught.
- **Confidence is lower than a direct hint** (0.88/0.80 vs 0.95/0.85). The
  edge assumes the route in force at link time served the call, so a stale
  route table would mislead; the price says so.

What it bought: `api-gateway → vets-service` stopped being "they share a
compose network" and became `GET /api/vet/vets → GET /vets`, matched against a
real extracted endpoint, citing `vet-list.controller.js:7` **and**
`application.yml:21` — the call and the route that justified it. That is the
difference between a container diagram and a call graph.

One caution retained from the original analysis: URL literals carrying both
host and path frequently live only in tests. Those are already classified and
excluded, and a naive "scan for URL literals" pass would manufacture test-only
edges. Don't regress that.

---

## Gap 2 — no ground-truth enumerator for most modalities — PARTLY CLOSED

> **Gateway routes now have one**, owed by the R7 gateway work: that resolver
> depends on the route table being complete, so a route the parser misses
> silently costs call edges. Messaging topics, package dependencies, gRPC
> services and GraphQL operations still have none.

`measure_recall.py` enumerates compose `depends_on`, Next.js route handlers,
MCP capability manifests and gateway routes. A category with no enumerator
contributes nothing to the recall numbers while looking like success — the
same trap as an uncovered calibration tier.

Adding one is small, self-contained, and the highest-yield contribution in the
repository. **Every enumerator written so far has found a real defect**, and
the gateway one found two within an hour:

- `yaml.safe_load` RAISES on multi-document YAML, and both the harness and
  `gateway_parser` caught that as "unparseable" and moved on. Spring configs
  are routinely multi-document (one `---` per profile), and anything deployed
  as Kubernetes manifests always is. The route table was being discarded
  whole, reported as a clean 0 of 0.
- The Python endpoint regex matched any quoted first argument to
  `.get(...)`, so every `dict.get("task_id")` in the corpus became a `GET`
  endpoint — and every `requests.get("/x")`, a CLIENT call, became a provider
  contract pointing the wrong way. It had manufactured **1,057 endpoint
  contracts that do not exist**, roughly a third of the headline count.

Neither was visible to the unit tests or to the precision pass, because
precision only judges edges that exist; it cannot see a category silently
reporting zero, and it samples rather than enumerates.

---

## Gap 3 — attribution inside a repo

`scope.ambiguous` runs high on estates whose service-name claims come from
root-level compose files: the path scope is the repo root, so the resolver
cannot decide which of N services owns a given file and correctly declines.
Correct, but it caps everything above it — code that cannot be attributed to a
service cannot contribute a call edge.

The lever is anchoring more `svcname` claims to a directory. Compose build
contexts do this well when present; many claims have none.

---

## Gap 4 — submodules are silently absent

`clone_repository` runs `git clone --depth 1 --filter=blob:none
--single-branch` with no `--recurse-submodules`, so a submodule directory
arrives empty and everything it contains is missing from the graph.

Whether to clone submodules is a genuine policy question — vendored upstream
code is third-party and often large. But the current behaviour is not a
decision, it is an accident: the graph reports on a repository with a
submodule-shaped hole in it and nothing records that the hole exists. At
minimum ingestion should count and report unfetched submodules so coverage is
not silently overstated.

This has already caused one wrong conclusion in this project's own history: a
body of publish/subscribe calls was attributed to a repository that contains
none of them, because the reader was looking at a working copy with submodules
initialised while the ingest saw an empty directory.

---

## Gap 5 — external boundaries have no node

Calls that leave the estate — a managed LLM gateway, a payment provider, a
partner API — currently either vanish or land on a bare hostname. They deserve
first-class external-boundary nodes, so "what does this system depend on that
we do not own?" becomes answerable.
