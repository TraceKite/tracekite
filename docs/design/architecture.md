# Adduce architecture

The design Adduce must have to be (a) embeddable as a library, (b) correct at
1,000 repositories, and (c) maintainable by people who did not write it.

This document is normative: it fixes *how the pieces fit together*, and
where any other document disagrees with it, this one wins.

---

## 1. Scope

Adduce establishes **what is connected across repositories, and how we know**.
It does not decide what to do about it. Incident triage, chat interfaces,
ranking, and retrieval belong to hosts.

Everything below follows from one constraint: **a host must be able to use
Adduce without adopting Adduce's infrastructure.**

---

## 2. Layering

```
┌──────────────────────────────────────────────────────────┐
│  adduce-ui          React                                 │  separate artifact
├──────────────────────────────────────────────────────────┤
│  adduce-server      FastAPI, jobs, auth, scheduling       │  optional extra
├──────────────────────────────────────────────────────────┤
│  adduce-store       GraphStore protocol + backends        │  the ONLY I/O
├──────────────────────────────────────────────────────────┤
│  adduce-parsers     bytes + path → claims                 │  pure
├──────────────────────────────────────────────────────────┤
│  adduce-core        claims, resolvers, evidence, confidence│  pure, no deps
└──────────────────────────────────────────────────────────┘
```

**Dependency rule: arrows point down only.** `core` imports nothing from the
layers above it. `parsers` may import `core`. `store` may import `core`.
`server` may import all. Nothing imports `ui`.

This is enforceable in CI with an import-graph check, and it should be — the
rule is worthless if it degrades silently.

### Current state

**Holds, and is enforced.** `backend/tools/check_layers.py` assigns
every module to a layer and walks the AST of each; it exits 0 today.

```
core 60 · parsers 64 · store 16 · server 29 · unassigned 0
```

A module missing from its `LAYERS` table is an error, not a default — new code
cannot join the tree unranked and quietly import whatever it likes. The same
tool also enforces that **a route may orchestrate but not compute**: a `for` or
`while` in a handler is logic a library host cannot reach, so `pip install`
would answer differently from `docker compose up`.

Four static checks gate a change, and each exists because its failure is
silent rather than loud:

| Tool | Catches |
|---|---|
| `check_layers.py` | an upward or sibling import; a route computing inline |
| `check_invariants.py` | a second key canonicaliser, a second id speller (I4), a cross-shard read (I10) |
| `check_annotations.py` | an annotation naming an unimported type — invisible on Python 3.14 (PEP 649 defers evaluation), an import-time `NameError` on the declared floor of 3.13 |
| `export_openapi.py --check` | `lib/api-spec/openapi.yaml` drifting from the routes it is generated from |

**What the layer check does and does not do.** The boundaries are declared and checked;
the files still live under `backend/adduce/`. Physically separating them into
installable distributions is a separate goal (`pip install adduce-core` pulling
no neo4j and no fastapi), and nothing above is a substitute for it.

The remaining coupling was, in the end, one module: **every
violation was `adduce/config.py`**, reached by ten modules across core and
store.
Core now owns `engine_config.EngineConfig` (config dir, workspace dir, HMAC
key) and store owns `db/store_config.StoreConfig` (bolt URI, credentials,
batch size) — both frozen dataclasses on stdlib alone, with working defaults.
`adduce/config.py` is the one place that binds an environment to them.

**The cost of that, stated plainly:** core no longer reads the environment, so
an entry point that never imports `adduce.config` runs on defaults. `main.py` and
`tools/calibrate.py` bind explicitly; anything new that does not will hash
config values under an empty HMAC key. This is loud rather than silent —
`redaction` raises `RedactionKeyMissing` — and the calibration CLI test pins
the ordering, because the fix is one line in the wrong place away from
regressing.

This section previously listed three violating files. Two of them never were:

| Claimed | Reality |
|---|---|
| `parsers/config_parser.py` imports storage | false positive — matches `"neo4j"`, a string in the table that detects which technologies a *scanned* repo uses. Its only imports are `logging`, `re`, `yaml`, `dataclasses`, `typing`. |
| `parsers/tree_sitter/adapter.py` imports storage | false positive — matches `"fastapi"` in `_framework_for_language()`, a language→framework map used to recognise routes in scanned code |
| `services/linker/service.py` reads Neo4j directly | real — imported `adduce.db.constraints` and `adduce.db.neo4j_client` for claims, fingerprints and orphan GC |

The real one is fixed by inversion rather than relocation: the linker declares
the storage a run needs as a Protocol it owns (`linker/ports.py`),
`services/linker_store.py` implements it against Neo4j by delegating to
`graph_writer`/`link_writer`, and the server composes the two. The linker now
names no backend, which is what the embeddable library builds on.

**The false positives are the lesson.** They came from searching text
in a codebase whose domain vocabulary *is* framework and database names — this
tool exists to read other people's `fastapi` and `neo4j` strings. An
import-graph check that greps will keep reporting exactly this error, so the
check must parse imports. Verified here with an AST walk: 2 violations in 1 file
before, 0 after.

---

## 3. Data model

Three stages, each an immutable value type. This is the contract a host
depends on, so it is versioned and frozen.

### 3.1 Claim — "I saw something at this location"

```python
ClaimRecord:
    id, repo_id, kind, direction, key
    service_hint, hint_source, matchable
    evidence: list[str]              # "path/to/file.py:42"
    attrs: dict
    evidence_node_id, evidence_node_type
```

A claim is a **local, unjoined observation**. `kind` is one of 21 (`http`,
`route`, `cfgdef`, `cfgread`, `grpcstub`, `topic`, `owner`, …). `direction` is
`in` or `out`. `key` is the rendezvous key — the string two sides must agree
on to meet.

**A claim never references another repository.** This is what makes extraction
shardable, and it is invariant I3 below.

### 3.2 Rendezvous — "two claims met on a key"

Claims group by `key`. A rendezvous is the group, plus the resolver that
formed it and the transformations it applied (gateway prefix strip, env
substitution, alias resolution).

The rendezvous is materialised, not implicit. That is the difference between
Adduce and a collision-hash design: because the join is a real object, it can
carry provenance, be explained, be declined, and be scored.

### 3.3 Edge — "these two things are connected, and here is the receipt"

An edge carries: type, both endpoints, confidence, the resolver chain that
produced it, and evidence spans on **both** sides.

An edge with evidence on only one side is a bug, not a weak edge.

### 3.4 Time — derived, not stored

The graph has a time dimension, and it is deliberately **not** a field on the
edge.

Each repo artifact is content-addressed and stamped with its `head_commit_sha`
"The graph as of commit X" is therefore not a query against versioned
edges — it is a compaction of the artifacts at X. Point-in-time falls out of
the artifact model already planned, at no storage cost and with no schema
change.

Everything in the temporal phase reduces to that:

| Want | Is |
|---|---|
| the graph at a commit | compact the artifacts at that commit |
| **PR mode** — what a branch changes | `compact(base)` vs `compact(head)`, diffed |
| when a dependency appeared | binary-search the artifact series |
| blast radius in March | compact March's artifacts |
| contract drift | declared side vs observed side at the same commit |

This is why determinism (I1) is load-bearing rather than tidy: **diffing two
graphs is only meaningful if identical inputs produce identical output.**
Without it every diff is noise and the whole temporal phase is unbuildable.
Incrementality is what makes the diff cheap enough to run per pull
request.

The consequence for sequencing: the temporal work needs no new data model, and
its real prerequisites are content-addressed artifacts, diffing and
incrementality — all of which the design already
delivers.

---

## 4. Execution model

The pipeline is a MapReduce, and stating it that way is what makes 1,000
repositories tractable.

```
  ┌── MAP ──────────────┐   sharded by FILE, parallel, cacheable
  │  files → claims     │   pure; no cross-repo reads
  └──────────┬──────────┘
             │
  ┌── BROADCAST ────────┐   small side tables, replicated to every worker
  │  gateway rules      │   O(rules)
  │  service aliases    │   O(services)
  │  env/config plane   │   O(config entries)
  └──────────┬──────────┘   built by its own map-reduce over config claims
             │
  ┌── NORMALIZE ────────┐   parallel; reads broadcast tables only
  │  gateway prefix strip│  ← R4/R7 path qualification
  │  service alias rewrite│ ← R0
  │  env substitution   │   ← R9
  └──────────┬──────────┘   claim keys are FINAL after this phase
             │
  ┌── SHUFFLE ──────────┐   partition by hash(rendezvous key)
  └──────────┬──────────┘
             │
  ┌── REDUCE ───────────┐   per partition, parallel
  │  resolvers R0–R14   │   hash join within partition + broadcast lookups
  └──────────┬──────────┘
             │
  ┌── MERGE ────────────┐   per-repo artifacts written in parallel,
  └─────────────────────┘   then compacted into one LinkRun
```

### Why NORMALIZE is a separate phase

**Gateway qualification and alias resolution change a claim's rendezvous key.**
R7 strips a gateway prefix; R0 rewrites a service alias; R9 substitutes an env
value. If those ran inside REDUCE, a claim would have to *move partitions
mid-resolution* — something the model cannot express, and a correctness bug,
not merely a slow path.

So key-rewriting is lifted into its own phase that runs **after** the broadcast
tables exist and **before** the shuffle. It reads only broadcast state, so it
parallelises exactly like MAP.

This is invariant I9: **a claim's rendezvous key is final once NORMALIZE
completes.** No resolver may alter a key during REDUCE.

### Sharding

| Phase | Shard by | Why not the obvious choice |
|---|---|---|
| MAP | **file** | sharding by repo puts 81% of the current estate on one worker — `ap` is 31,320 of 38,696 nodes. Parsers are per-file pure functions, so file-level sharding is free. |
| NORMALIZE | claim | pure, stateless given broadcast |
| SHUFFLE / REDUCE | **module**, via hash(key) | a repo is how code is stored; a module is what owns behaviour. `module_of` already exists and is already the boundary elsewhere. |
| MERGE | repo artifact | N artifacts, N writers, no write contention |

### Why this works

The join is **already a hash join**, not an all-pairs scan. `r7_http.py` builds
`providers: dict[(method, path) → [Provider]]` and looks up candidates by key;
`ClaimIndex` maintains `_by_kind` and `_by_kind_key`. Rendezvous is a group-by,
which is O(N), streamable, and shardable.

The resolvers that need global context — R4's longest-prefix gateway match, R0
aliases, R9's env plane — read from `rewrite_routes`, `service_by_name`,
`env_values`. These are **broadcast side tables**, bounded by the number of
services and rules, not by claim volume.

Partitioned hash join + broadcast side tables is a shape that scales linearly
and shards cleanly. The expensive half of the design is already correct; what
remains is plumbing.

### Measured before designing the parallel work

The table below was written against extrapolation. These are measurements,
taken with `backend/tools/scale_probe.py` and against the live six-repo
estate, and two of them change where parallelism is worth spending.

| | real estate (6 repos, 3,089 claims) | synthetic (300 repos, 1,000 claims) |
|---|---|---|
| load claims from Neo4j | 0.12 s | — |
| **JOIN — every resolver** | **0.03 s** | 0.02 s |
| MAP (scan + parse) | — | 0.32 s, **94% of total** |
| largest rendezvous key | 21 claims, **0.9%** | 10.0% |
| top-10 keys | 5.9% | 51% |

**The join is not the bottleneck, and is not close to being one.** The whole
resolver pipeline over the real estate runs in 30 milliseconds. GOAL.md's "a
full link takes ~10 seconds" is therefore **write I/O, not compute** — the
time is in getting edges into Neo4j, not in deriving them.

That is a correction with consequences. The goal was "link time scales
inversely with workers", and parallelising REDUCE would divide 0.03 s. The
work is in MAP, whose share *grows* with repository count (87% → 94% across
the probe), and in the write path. **Parallelism belongs in MAP, with batched
writes; a parallel REDUCE is not worth building yet** and REDUCE
partitioning is premature until the join is a measurable fraction of anything.

**Skew is mild in reality and severe under replication.** The real estate's
largest key holds 0.9% of claims; a synthetic estate of identical repos puts
10% on one key, because every copy calls the same contract. The skew guard
should be sized against the synthetic worst case — a thousand services calling one
popular contract is a real shape — but it is not urgent at the observed
distribution.

Caveat, stated because it bounds the conclusion: the synthetic repos are three
files each, so the absolute MAP numbers understate a real estate where one
monorepo is 81% of the nodes. The *ratio* between phases is the finding, not
the seconds.

### What must change

| Change | Why |
|---|---|
| `load_claims()` → partitioned iterator | today it materialises the whole estate in one list |
| per-repo content-addressed artifacts | unchanged repos must be skipped, not re-parsed; also gives parallel writes |
| claim-level invalidation | one repo pushing must not re-resolve the estate |
| parallel map and parallel reduce | 1,000 repos cannot run serially |
| **lift key-rewriting out of REDUCE into NORMALIZE** | correctness: keys must be stable across the shuffle |
| **shard MAP by file, not repo** | one monorepo is 81% of the estate |
| **partition REDUCE by module, not repo** | same reason, on the join side |
| **skew guard on hot rendezvous keys** | one popular contract otherwise serialises the reduce |

---

## 5. Storage

### 5.1 The protocol

```python
class GraphStore(Protocol):
    def upsert_nodes(self, nodes: Iterable[Node]) -> None: ...
    def upsert_edges(self, edges: Iterable[Edge]) -> None: ...
    def query(self, spec: QuerySpec) -> Result: ...
    def delete_by_run(self, link_run_id: str) -> None: ...
```

`QuerySpec` is a typed description — neighbourhood, bounded path, aggregate —
**not a query string.** A backend that only speaks SQL must not have to parse
Cypher.

### 5.2 Backends

| Backend | Role |
|---|---|
| **SQLite** | default; also the artifact format |
| Neo4j | opt-in, for teams already running it |
| DuckDB | global compaction — merging N artifacts is columnar analytics |
| in-memory | tests |

### 5.3 Why SQLite is the default

A SQLite file *is* the portable artifact. One decision satisfies the
zero-infrastructure default, the per-repo artifact format, and byte-level
determinism at once.

The traversal port is small: there are exactly **four** variable-length
queries in the codebase, all bounded (`*1..n`, `max_hops ≤ 8`) with edge-type
predicates. `shortestPath` is deliberately never used — which is the one thing
that is genuinely hard in SQL. Recursive CTEs cover the rest.

Measured lock-in: zero APOC, zero GDS, zero full-text, zero vector. Portable
Cypher only.

### 5.4 Embedding: no store at all

A host that embeds Adduce supplies its own storage, or none:

```python
claims = [scan(path=p, repo_id=r) for r, p in repos]
result = link(claims)          # pure: edges + declines + evidence
host.write(result.edges)       # host owns persistence
```

This is not a convenience. A host that already runs a graph database must not
be made to run a second one to use Adduce.

---

## 6. Invariants

Violating any of these is a defect, not a trade-off.

| | Invariant |
|---|---|
| **I1** | **Determinism.** Same inputs + same version → byte-identical artifact. Stable ordering; no wall-clock or map-iteration order in payloads. Without this, caching, diffing, and incrementality are all impossible. |
| **I2** | **Purity.** `core` and `parsers` perform no I/O. All I/O lives in `store`. |
| **I3** | **Locality.** A claim is derived from exactly one repository. No cross-repo reads during map. |
| **I4** | **Key and id discipline.** Rendezvous keys come from one canonicaliser (`utils/canonical.py`) and rendezvous node ids from one speller (`utils/rendezvous_ids.py`). No resolver invents either format. Both halves fail the same way — silently, as claims that never meet or a reader that finds nothing — so both are enforced by `check_invariants.py`. |
| **I5** | **Decline discipline.** Every unresolved claim increments a named counter. Silence is a bug; a decline is data. |
| **I6** | **Evidence completeness.** Every edge cites file and line on **both** sides. |
| **I7** | **Run immutability.** A `LinkRun` is append-only; every edge is attributed to exactly one run. |
| **I8** | **Broadcast bounds.** Side tables are O(services + rules + config), never O(claims). |
| **I9** | **Key finality.** A claim's rendezvous key is final once NORMALIZE completes. No resolver may alter a key during REDUCE. |
| **I10** | **Shard independence.** No phase may require two shards to communicate. Cross-shard need means the work belongs in BROADCAST or NORMALIZE. |

**I8 and I9 are the load-bearing ones.**

I8: the moment a resolver needs a side table proportional to claim count, the
estate stops sharding. Any new resolver must be checked against it.

I9: the moment a resolver rewrites a key after the shuffle, claims belong to
the wrong partition and edges are silently lost. This is a correctness
invariant, not a performance one.

---

## 7. Scale

### 7.1 Measured baseline

6 repositories, real:

| | |
|---|---|
| nodes | 38,696 |
| edges | 62,854 |
| claims | 3,089 |
| largest single repo (`ap`) | 31,320 nodes — 81% of the estate |

### 7.2 Extrapolation to 1,000 repositories

| Mix | Nodes | Edges | Claims |
|---|---|---|---|
| all small-service repos | ~1.5M | ~2.4M | ~0.5M |
| 10% monorepos | ~4.5M | ~7M | ~1.5M |

**Storage is not the constraint.** 7M edges is roughly a 1 GB SQLite file.

**Incrementality is the constraint.** Without it, one push re-resolves 1.5M
claims — O(estate) work for an O(1) change. That is what breaks at 1,000
repositories, not the database.

### 7.3 Link time — measured, then projected

Full link over the current estate (6 repos, 3,089 claims) takes **2.6–12.0 s**
wall-clock. Taking 10 s as the full-pass figure and assuming the hash join
stays linear:

| Estate | Claims | Link time |
|---|---|---|
| today | 3,089 | ~10 s |
| 1,000 repos, single-threaded | ~1.5 M | **~81 min** |
| 1,000 repos, 16 workers | ~1.5 M | ~5 min |
| 1,000 repos, 64 workers | ~1.5 M | ~76 s |
| 1,000 repos, incremental (1 repo changed) | ~1.5 K touched | seconds |

81 minutes is unacceptable, 5 minutes is fine, and incrementality makes the
common case a non-event. That is the entire argument for the phased,
shardable pipeline.

### 7.4 Horizontal scaling by component

| Component | Horizontal? | Shard key | Real ceiling |
|---|---|---|---|
| Clone / fetch | ✅ perfect | repo | **git host rate limits**, not CPU |
| MAP (parse) | ✅ perfect | **file** | I/O saturation; unchanged repos cost zero |
| BROADCAST | ⛔ replicated | — | by design; I8 keeps it a few MB |
| NORMALIZE | ✅ perfect | claim | none — pure over broadcast state |
| SHUFFLE | ✅ | hash(key) | ~750 MB moved ≈ 6 s at 1 Gbps. **Skew, not volume** |
| REDUCE | ✅ | module partition | skew on hot keys |
| MERGE (write) | ✅ with artifacts | repo | a single shared DB serialises here; artifacts do not |
| Query / traversal | ✅ read replicas | — | stateless |
| API | ✅ trivially | — | stateless |
| UI | ❌ | — | rendering limit — needs aggregate views, not more infra |

The serial residue is the broadcast build and the compaction merge. Both are
cheap filter-and-collect passes, and both are themselves map-reduces.

### 7.5 Measured, not extrapolated

§7.5 used to say the 1,000-repo figures were extrapolation. They are now
measurement, on the synthetic estate `tools/synth_estate.py` generates —
ground truth by construction, so a timing is always of an estate that
provably linked *correctly*: every planted call found, **0 false
positives**.

The standing verification size is **≤ 100 repositories** — scaling shape is
what matters, and it is fully visible there (operator decision, 2026-07-29).
100 repos, 2,526 files, 8-core laptop, 326/326 planted calls verified:

| | serial | 2 workers | 4 | 8 |
|---|---|---|---|---|
| MAP (scan → artifacts) | 5.9 s | 3.1 s (1.90×) | 1.7 s (3.48×) | 1.1 s (**5.19×**) |

Link time scales inversely with workers — the criterion, measured.

A one-time run at 1,001 repos (25,814 files, 16,556 claims, one 20-service
monorepo, 3,374/3,374 calls verified) confirmed nothing bends at 10× the
routine size: MAP 60.0 s → 11.3 s at 8 workers (5.30×), and the join stays
trivial — **0.19 s**, the earlier finding intact at scale. A REDUCE worker pool
would divide 190 ms and add process startup; it stays unbuilt until a
measurement says otherwise.

**One push: 5.8 s** end to end — 1,000/1,001 repos reused by fingerprint
one rescanned (2.8 s), relinked (0.15 s). Seconds, not the 81 minutes
§7.3 projects for the serial case. Of the 5.8 s, **2.9 s was reading every
artifact back to relink** — closed: `read_claims` selects the ~2% of
artifact rows that are claims instead of materialising the graph, taking
the 100-repo read from 0.20 s to 0.02 s and the repush to **0.54 s**, all
of it the one rescan. Link-side memory is O(claims), not O(nodes), which
is what lets peak memory stay flat as the estate grows.

Two caveats the numbers do not carry on their face:

* The synthetic estate is **claim-sparse**: ~16 claims/repo where the real
  estate averages ~500. MAP cost is realistic (file count is), but the join
  and shuffle are underloaded by ~30×. Skew and partition sizing needs a claim-dense
  variant before either is designed.
* Skew was measured (largest key holds 1.9% of matchable claims) but not
  *stressed* — the hot key share is configurable and the guard does
  not exist yet.

**File-level MAP sharding, measured.** A 21-repo estate whose monorepo holds 55%
of the files caps repo-granular sharding at 1/0.55 ≈ 1.82×; it measured
1.71× at 8 workers. File-sharding the monorepo (`sharded_scan.py` —
structure once in the parent, contiguous file slices in workers, chunks
merged in slice order) measured **2.45×**, above the repo-sharding ceiling,
which is only possible if the monorepo actually spread. All three runs
produced byte-identical artifacts, which is the whole contract: a repo must
not hash differently because of how many workers scanned it. The REDUCE
half stays unbuilt — partitioning a 0.19s join divides milliseconds
and adds a shuffle; the measurement, not the plan, decides when that changes.

---

## 8. Automation and triggers

The design principle:

> **Manual actions are opt-in refinements, never preconditions.** The graph
> must be complete and current without anyone touching it.

### 8.1 Current state

| Step | Today |
|---|---|
| ingest → link | ✅ **automatic**, and coalesced — `_ingest()` calls `_enqueue_relink()`, so a burst of ingests yields one link run |
| which repos exist | ❌ manual — someone POSTs each repo |
| when to refresh | ❌ manual — nothing watches. No webhook, no poll, no schedule |
| submodules | ❌ never fetched (599 uncounted calls) |
| review-queue decisions | manual **by design** — and must never block the graph |

The first row is better than the docs claimed; the middle rows are the gap.

### 8.2 Two trigger models

**A · Server-pull** — for small and medium estates.

| Layer | Mechanism |
|---|---|
| discovery | enumerate an org, group, or directory (`github:org/*`) rather than naming repos; re-run periodically to pick up new ones |
| change detection, preferred | **webhook** — git host POSTs on push → refresh that repo |
| change detection, fallback | **poll `git ls-remote`** — compares head SHA without cloning; works without webhook permissions |
| change detection, backstop | **schedule** — a nightly sweep catches whatever the first two missed |
| coalescing | already implemented for link runs; extend to ingest |
| resilience | retry with backoff; flag repos whose head SHA moved but never re-ingested |

**B · CI-push** — for large estates.

Each repository's own CI runs `adduce scan` on merge and uploads its artifact;
a compactor merges them. No central watcher, no polling, no rate limit — the
work happens where the code already is.

**At 1,000 repositories, model B is the correct one.** Polling 1,000 repos from
one server runs straight into the ceiling named in §11.1: fetch is bounded by
someone else's quota. Model B removes fetch from the critical path entirely.

Model B is the GitHub Action plus artifacts and compaction — the
automation story and the scale story are the same work.

### 8.3 What stays manual

Review-queue decisions and calibration labelling are human judgement; that is
the point of them. The requirement is that neither is ever a **precondition** —
an unreviewed decline must not withhold an edge, and an uncalibrated tier must
not block a run. They refine the graph; they do not gate it.

---

## 9. Failure modes

| Mode | Handling |
|---|---|
| **Partition skew** — `GET /health` exposed by 800 services lands in one partition and serialises the reduce | detect hot keys during shuffle; split the partition or dedicate a worker |
| **Monorepo dominance** — one repo is 81% of the estate | shard MAP by file; partition REDUCE by module. `module_of` is already the boundary |
| **Key rewritten after shuffle** — claim lands in the wrong partition, edge silently lost | structurally prevented: key-rewriting only happens in NORMALIZE (I9) |
| **Write contention** — many workers, one database | per-repo artifacts: N files, N writers, compacted afterwards |
| **Clone rate-limiting** — 1,000 repos against one git host | token pool + backoff; fetch is the one phase bounded by an external quota |
| **Unfetched submodules** — declared but never cloned (599 uncounted calls today) | report at ingest as a coverage gap, never silently |
| **Ambiguous gateway prefix** | already declines with `r7.gateway_prefix_ambiguous`; keep |
| **Schema drift between artifact versions** | `schema_version` on every artifact; refuse to compact across incompatible majors |
| **Evidence rot** — cited line no longer says what we claimed | re-verification pass; downgrade confidence rather than delete |
| **Runaway repository** | resource caps per phase: max files, max claims, timeout |

---

## 10. Decision record

| ID | Decision | Rationale |
|---|---|---|
| **AD1** | Library core, application shell | a host cannot depend on an application; the core is already 97% pure |
| **AD2** | Storage behind a protocol; SQLite default; **no store required for embedding** | a host may already run a different graph database — requiring Neo4j would mean two graph databases for one graph |
| **AD3** | Join is a partitioned hash join with broadcast side tables | the only shape that shards; already how the resolvers are written |
| **AD4** | Content-addressed per-repo artifacts are the unit of caching, portability, and incrementality | one construct serves three needs |
| **AD5** | Determinism is a hard invariant, not a goal | everything downstream depends on it |
| **AD6** | Decline-don't-guess stays; declines are recorded data | precision is the product; 189 TP / 0 FP is the thing worth protecting |
| **AD7** | Import SCIP/LSIF for symbol-level calls rather than growing our own resolver | the 168-line resolver is the measured weak point; rebuilding graphify's 2,702-line one is building someone else's product |
| **AD8** | **NORMALIZE is a distinct phase** between BROADCAST and SHUFFLE | gateway/alias/env rewriting changes rendezvous keys; doing it after the shuffle puts claims in the wrong partition. Correctness, not performance |
| **AD9** | **Shard MAP by file, partition REDUCE by module** — never by repo | one monorepo is 81% of the current estate; repo-level sharding leaves 15 of 16 workers idle |

---

## 11. Component reference

Every component, its contract, how it shards, and what actually limits it.
"State" is what exists today, not what is planned.

### 11.1 FETCH — `ingest_source.py`, `repo_service.py`

| | |
|---|---|
| Contract | repo spec → working tree + `head_commit_sha` |
| Shard key | repo |
| Scaling | perfect — repos are independent |
| **Ceiling** | **git host rate limits and network, never CPU.** 1,000 repos × ~50 MB ≈ 50 GB |
| State | exists, serial. Needs a token pool + backoff, and **submodule reporting** (599 calls currently uncounted) |

### 11.2 SCAN — `file_scanner.py`, `file_classifier.py`

| | |
|---|---|
| Contract | working tree → classified file list (source / test / vendored / generated) |
| Shard key | directory subtree |
| Scaling | perfect; pure over the filesystem |
| Ceiling | inode traversal on very large monorepos |
| State | exists. Classification is precision-critical — it is what keeps test fixtures out of the graph |

### 11.3 PARSE — `parsers/*` (26), `services/*_extractor.py` (11)

| | |
|---|---|
| Contract | `(bytes, path, language) → claims` |
| Shard key | **file** — never repo (AD9) |
| Scaling | perfect and cacheable; unchanged files cost zero |
| Ceiling | I/O and tree-sitter parse time |
| State | exists, serial per repo. Two files import storage and must be made pure |

The largest single lever in the whole pipeline: content-addressed caching here
means a 1,000-repo estate re-parses only what changed.

### 11.4 CLAIM EMISSION — `claims.py`, `ingest_claims.py`, `ingest_artifacts.py`

| | |
|---|---|
| Contract | extractor output → `ClaimRecord` with evidence spans |
| Shard key | file |
| Scaling | perfect |
| Ceiling | none |
| State | exists. Enforces I3 (a claim derives from exactly one repo) and I6 (evidence on both sides) |

### 11.5 BROADCAST BUILD — derived from `cfgdef` / `svcname` / gateway claims

| | |
|---|---|
| Contract | all config-bearing claims → `rewrite_routes`, `service_by_name`, `env_values`, `module_services` |
| Shard key | none — the output is replicated, not partitioned |
| Scaling | **a barrier**, but itself a map-reduce (map: per-repo config claims; reduce: union) |
| **Ceiling** | **invariant I8** — must stay O(services + rules + config). A few MB at 1,000 repos |
| State | exists, built inline inside `LinkContext.__init__`. Needs lifting into a phase with its own artifact |

### 11.6 NORMALIZE — `linker/normalize.py`

| | |
|---|---|
| Contract | `(claim, broadcast) → claim with final rendezvous key` |
| Shard key | claim |
| Scaling | perfect — pure over broadcast state |
| Ceiling | none |
| State | exists. `engine.py` runs BROADCAST, then NORMALIZE, then JOIN, so every rendezvous key is final before the shuffle (I9). The rewriting that used to sit inside R0/R4/R7/R9 happens here now |

### 11.7 SHUFFLE — *does not exist yet*

| | |
|---|---|
| Contract | claims → partitions keyed by `hash(rendezvous key)`, bucketed by module |
| Shard key | module |
| Scaling | network-bound: ~750 MB at 1,000 repos ≈ 6 s at 1 Gbps |
| **Ceiling** | **skew, not volume** — one hot contract serialises the reduce |
| State | missing |

### 11.8 REDUCE — `linker/r0_alias.py … r14_operation.py`, `linker/base.py`

| | |
|---|---|
| Contract | partition of claims + broadcast → edges + declines |
| Shard key | module partition |
| Scaling | perfect per partition; already a hash join, not an all-pairs scan |
| Ceiling | skew; per-resolver cost |
| State | exists, single-threaded, whole estate in memory via `load_claims()`. Algorithm is right; the plumbing is not |

### 11.9 FUSE + ROLLUP — `linker/base.py::fuse_edges`, `linker/rollups.py`

| | |
|---|---|
| Contract | edges → deduplicated edges; `INVOKES` → `CALLS_SERVICE`, cross-repo signals → `DEPENDS_ON_REPO` |
| Shard key | partition, then a global pass for repo-level rollups |
| Scaling | fuse is per-partition; `DEPENDS_ON_REPO` needs a global view but operates on a small aggregate |
| Ceiling | negligible |
| State | exists. Rollups carry weight/via/min/max confidence and `evidence_edge_ids` |

### 11.10 CALIBRATE — `calibration.py`

| | |
|---|---|
| Contract | edges + labelled estate → confidence scores |
| Shard key | none — needs the whole edge set |
| Scaling | a barrier, but cheap |
| Ceiling | availability of labelled estates, not compute |
| State | exists. Every priced tier requires an estate or the test fails — keep that gate |

### 11.11 WRITE — `link_writer.py`, `graph_writer.py`, `graph_factories.py`

| | |
|---|---|
| Contract | edges + `link_run_id` → persisted graph |
| Shard key | **repo artifact** |
| Scaling | ✅ with artifacts (N files, N writers); ⛔ with one shared database |
| **Ceiling** | a single Neo4j tops out ~10–50k edges/sec batched → 2–12 min for 7 M edges |
| State | exists, single Neo4j. This is the component the artifact model (AD4) exists to fix |

### 11.12 COMPACT — `db/artifact.py::compact`

| | |
|---|---|
| Contract | N repo artifacts → one global index + deltas |
| Shard key | key range |
| Scaling | columnar analytics; parallel by key range (DuckDB) |
| Ceiling | merge fan-in |
| State | exists. `ATTACH` + `INSERT OR REPLACE` across artifacts, so a re-scanned repo supersedes its own rows; an unreadable or wrong-version artifact is skipped **and named**, never dropped |

### 11.13 STORE — `db/neo4j_client.py` → `GraphStore` protocol

| | |
|---|---|
| Contract | `upsert_nodes`, `upsert_edges`, `query(QuerySpec)`, `delete_by_run` |
| Shard key | backend-specific |
| Scaling | reads scale by replica; writes by artifact |
| Ceiling | backend-specific |
| State | Neo4j only, no protocol. `QuerySpec` must be a typed description, never a query string |

### 11.14 QUERY / TRAVERSAL — `graph_reader.py`, `routes/trace.py`

| | |
|---|---|
| Contract | `QuerySpec` → neighbourhoods, bounded paths, aggregates |
| Shard key | none — stateless reads |
| Scaling | horizontal via read replicas |
| Ceiling | bounded traversal (≤ 8 hops, type-predicated) on 7 M edges is single-node work |
| State | exists. **Four** variable-length queries total; `shortestPath` deliberately unused |

### 11.15 ORCHESTRATION — `job_queue.py`, `job_handlers.py`, `ingestion_service.py`

| | |
|---|---|
| Contract | schedule and track fetch/parse/link runs |
| Shard key | job |
| Scaling | needs a real work queue at 1,000 repos |
| Ceiling | queue throughput |
| State | exists, in-process. Becomes the worker pool when MAP is parallelised |

### 11.16 API + UI — `routes/*`, `frontend/src`

| | |
|---|---|
| Scaling | API stateless → horizontal. UI uses grouped entry plus bounded Module/Focus/Impact projections |
| Ceiling | server responses still load per-repo samples; a client roll-up is not a 1,000-repo backend aggregate |
| State | frontend roll-up exists; `MAX_SCOPE_REPOS` and `GRAPH_DETAIL_NODE_LIMIT` bound rendering. Authoritative backend aggregates/totals are still needed |

### Cross-cutting

| Component | Note |
|---|---|
| `redaction.py` | secrets must never reach a claim, an artifact, or a log |
| `call_graph_resolver.py` | 168 lines — the measured weak point; replaced by SCIP import (AD7) |
| counters (`ctx.count`) | invariant I5; the raw material for every counter, timing and log a run reports |
