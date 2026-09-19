# Incremental scan, and file-level context for agents

**Status:** proposal. Every "today" claim below was verified by reading or
running the code at `02c1d38`; every "proposed" item is unbuilt.

The short version: an agent editing one file needs that file's references, and
the graph can already answer that. What it cannot do is *stay current cheaply* —
a one-byte edit re-parses the whole repository. The fix is smaller than it looks,
because the file-subset parse, the deterministic merge, and the incremental join
all already exist and are already tested.

---

## 1. The problem

`scan_if_changed()` ([reingest.py](../../backend/tracekite/services/reingest.py))
compares one whole-repository fingerprint. If it differs at all, `scan()` re-parses
every file.

> Change one byte in one file → re-parse the entire repository.

On this repo that is 378 source files and 2.2 MB re-parsed to pick up a one-line
edit. For an agent editing in a loop, that is the whole cost.

### The leaves are computed, then thrown away

`source_fingerprint()` already hashes every file individually. Its own docstring
calls it *"a Merkle-style digest over the files a scan would read."* But:

```python
per_file.append(f"{info.path}:{body}")   # sha256 per file, computed…
rolled = hashlib.sha256()
for entry in sorted(per_file):
    rolled.update(entry.encode())        # …folded into one, leaves discarded
```

So it answers **"did anything change?"** and cannot answer **"which files?"**
The artifact stores only the folded result: its schema is three tables —
`nodes`, `edges`, `artifact_meta` — with `source_digest` a single row in the last.

**That discard is the entire gap.** Nothing else about incrementality is missing.

---

## 2. What already exists

Verified. None of this should be rebuilt.

| Capability | Where | State |
|---|---|---|
| Per-file hashing | `reingest.source_fingerprint()` | Computes, then discards |
| File-subset parsing | `scan.parse_files(repo_id, files, file_ids, sink)` | **Exists** — the expensive half, already takes a slice |
| Per-file parse unit | `scan._parse_one_file()` | Exists |
| Deterministic chunk assembly | `sink_merge.merge_chunk()` | Exists, order-preserving |
| Parse-in-slices, merge-in-order | `sharded_scan.py` | Exists; byte-identical to serial |
| Byte-identity acceptance test | `test_sharded_scan.py:61` | `assert sharded.digest == serial.digest` |
| Incremental linking | `linker/incremental.relink()` | Exists, equivalence-tested |
| Claim → file mapping | `ClaimRecord.primary_path` | Exists and **is populated** (`src/billing_client.py`) |
| Neighborhood projections | `graph_reader.py` view presets | Exists — `code` view is `CONTAINS/DECLARES/CALLS` |
| Bounded traversal primitive | `GraphStore.Neighbourhood` | Exists |
| Per-node summary slot | `GraphNode.summary` | Field exists, **dormant** — nothing writes it |
| File watcher | — | **Does not exist** |

### The join needs nothing from us

`relink(claims, prior_claims, prior, *, ...)` takes **both full claim lists** and
computes the delta itself. It does not want a changed-file set. Incremental linking
is solved; the bottleneck is one stage earlier, in scanning.

---

## 3. The design

**Incremental scan is a third execution strategy beside serial and sharded, held
to the same contract.**

`sharded_scan` already establishes the pattern: build structure once in the parent,
parse contiguous slices of the ordered file list, merge chunks in slice order,
produce an artifact byte-identical to the serial scan. An incremental scan is the
same shape with one substitution:

> Sharded scan sources its chunks from **worker processes**.
> Incremental scan sources unchanged chunks from the **previous artifact**.

```
  previous artifact ──▶ per-file digests ──┐
                                           ├──▶ changed set
  working tree ──────▶ per-file digests ──┘
                                           │
              ┌────────────────────────────┴───────────────┐
              ▼                                            ▼
     unchanged files                                 changed files
     reuse cached chunk                          parse_files(...)  ← exists
              │                                            │
              └──────────────▶ merge_chunk() ◀─────────────┘
                               in file order                ← exists
                                     │
                                     ▼
                          artifact  (digest MUST equal
                                     a full serial scan)
                                     │
                                     ▼
                     relink(claims, prior_claims, prior)    ← exists
```

### Two invariants this must not break

**Ordering.** `sink_merge` preserves determinism only because chunks are
*contiguous slices of the ordered file list, merged in slice order*. A mixed
cached/fresh assembly must reproduce that exact order. Assemble by walking the
ordered file list and taking each file's chunk from cache or from a fresh parse —
never by concatenating "all cached, then all fresh."

**The claim budget.** The serial loop stops *before* the file that would exceed
`max_claims`, so files past the cap are never opened. `sharded_scan` cannot
reproduce that mid-list break and therefore discards a capped merge and re-runs
serially. **Incremental scan must take the same fallback**, for the same reason:
a cached chunk from a run that capped at a different point is not reusable.

### Acceptance test

The contract is byte-identity, and its template already exists:

```python
assert incremental.digest == serial.digest    # mirrors test_sharded_scan.py:61
```

Same repository, same bytes, any strategy. Determinism is what makes content
addressing, PR diffing, and cache reuse work at all — an incremental scan that is
merely *close* is worse than none.

---

## 4. File-level context for an agent

### What the graph can already answer

There is **no file→file reference edge**, and adding one is not required.
Ingestion's `DEPENDS_ON` is `file → external package` from the manifest parser.
File-to-file reachability is transitive:

```
file →CONTAINS→ symbols →CALLS→ symbols →CONTAINS⁻¹→ files
```

`graph_reader`'s `code` view already projects exactly this — `CONTAINS`,
`DECLARES`, `CALLS` over `Folder / File / Class / Interface / Method / Function`,
with a limit and a node priority. It is reachable from the UI's routes but **not
exposed to agents**, which is the real gap.

**Proposed:** one MCP tool returning that projection for a path, with `file:line`
on every element. Reuse the existing preset; do not write a second projection.

### Why the summary field should stay dormant

`GraphNode.summary` exists and nothing populates it. Filling it with model-written
prose breaks three things:

1. **Determinism.** The artifact is content-addressed — *"the name carries a digest
   of the bytes."* A summary is not reproducible, so re-summarizing changes the
   artifact digest with no source change, breaking `is_unchanged()`, PR diffing and
   reuse. `GOAL.md` calls determinism *"a shipped guarantee, not a convenience."*
2. **It cannot be cited, so it cannot be re-verified.** `tracekite reverify` checks
   citations against the current tree and downgrades rot. Prose has no mechanical
   equivalent: it would be the one artifact in the system able to go silently wrong,
   in a tool whose premise is that nothing is asserted without a citation.
3. **Cost**, recurring, across every node on every change.

**Serve a derived neighborhood, do not store a written summary.** Derived means
never stale, citable, and free.

### If prose is still wanted

A one-line "what is this file for" genuinely helps an agent decide whether to open
a file. The compatible shape:

- Store it **outside the artifact**, in a sidecar.
- **Key it by the file's content digest.** A changed file has a different key, so a
  stale entry is never read — staleness becomes structurally impossible and needs no
  invalidation logic.
- Mark it non-evidential: a hint for routing attention, never a substitute for a
  citation.

This falls directly out of persisting the leaves, which is why it belongs here.

---

## 5. Real time: one watcher, not many bots

Autonomous agents updating a shared graph reintroduce what freshness was meant to
prevent. Two overlapping re-links produce a torn graph — worse than a stale one,
because it looks current.

```
fs event → debounce → per-file digests → changed set
        → parse changed → merge in order → relink()
```

One process, one serialized queue, ordered, deterministic. No watcher exists today
(no `watchdog`, `watchfiles`, or `inotify` anywhere in the tree), so this part is
genuinely new — and it is the small part.

### On "no stale content"

Absolute freshness is the wrong target, and the codebase has already taken the
better position. `FreshnessState` carries four values — `CURRENT`, `STALE`,
`UNVERIFIABLE`, `UNKNOWN` — and `CompletenessAssessment.safe_to_delete` **always
returns `False`**.

The stance is not *never stale*. It is **never stale silently**. Chasing absolute
freshness costs unbounded work and still fails at the edges; typed, visible
staleness is achievable and is what lets an agent know when to distrust an answer.

---

## 6. Explicitly out of scope

- **A file→file import edge.** Transitive `CONTAINS`/`CALLS` answers the question;
  a new edge type would duplicate it and must clear the writer allowlist and the
  0-FP bar for no gain.
- **Partitioning the join.** Measured at 0.19s for 16.5K claims. `sharded_scan`
  already declines this for the same reason; the measurement decides, not the
  roadmap.
- **Summaries inside the artifact.** §4.

---

## 7. Staging

| # | Change | Size | Unlocks |
|---|---|---|---|
| 1 | Persist per-file digests — a `files(path, sha256)` table; `source_fingerprint()` already computes them | small | "which files changed" |
| 2 | Cache per-file parse output and assemble via `parse_files` + `merge_chunk` in file order | medium | one-file edits stop re-parsing the repo |
| 3 | Byte-identity test against a serial scan | small | the correctness contract |
| 4 | Expose the `code` view per path over MCP | small | the agent-facing payoff |
| 5 | Watcher + debounced serial queue | medium | real-time |
| 6 | *(Optional)* summary sidecar keyed by file digest | small | prose hints, never stale |

**(1)–(3) are the unlock**, and (3) is what makes (2) safe to believe. (4) is
independent of the rest and could ship first.
