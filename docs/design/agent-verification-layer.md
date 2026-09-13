# TraceKite as the verification layer for coding agents

**Status:** proposal, plus a status correction. The idea in §3 is largely
*already built*; §5 records where three documents now disagree with the code,
which is the most actionable part of this file.

---

## 1. The thesis

Coding agents can write code. The bottleneck has moved to **verifying what they
claim about it.**

An agent finishing a change asserts things that are structural, falsifiable, and
invisible to tests:

> "Nothing else uses this." · "I checked all the callers." · "This is safe to remove."

A reviewer cannot take those on trust, so they re-derive each one by hand — which
costs roughly what doing the work cost. **Agent throughput is therefore capped by
human review bandwidth, not by model capability.** That is the scaling wall.

Tests do not help here. A test proves the code you kept still works; it says
nothing about the consumer in another repository that you never knew to look for.

**The claim worth making machine-checkable is the impact claim.** "This change
affects these N consumers" is falsifiable, and TraceKite can adjudicate it
deterministically, offline, in CI, with a file and line for each.

---

## 2. Why TraceKite specifically

Three properties, all load-bearing, none of which an LLM-based code indexer can
offer:

| Property | Why it matters here |
|---|---|
| **Determinism** — identical inputs yield byte-identical artifacts | A claim becomes *re-derivable by a third party*. CI can recompute the agent's answer and compare. Without this, every diff is noise. |
| **Provenance** — `file:line` on **both** sides of every edge | The reviewer checks in five seconds instead of re-deriving. An assertion you can audit is worth more than one you must believe. |
| **Calibrated declining** — 189 TP / 0 FP, plus an explicit coverage model | The system distinguishes *"no consumers"* from *"I could not tell."* Almost nothing else in this category does. |

The third is the rarest and the most underrated. `CompletenessAssessment`
([completeness.py](../../backend/tracekite/completeness.py)) is conservative by
construction, and `safe_to_delete` is a property that **always returns `False`** —
a deliberate refusal to let any caller read an empty result as permission. That is
the correct primitive for an agent, which otherwise treats silence as absence.

---

## 3. The idea: the impact receipt

Every agent-authored change ships with a **machine-checkable evidence artifact**,
not prose.

- The agent states its claimed blast radius.
- CI **re-derives** it from the same inputs and compares.
- A mismatch fails the build and names the consumers the agent missed, each cited.

This converts agent output from *"trust me"* to *"verify me"* — and the
verification is cheap, because it is a diff of two deterministic artifacts rather
than a second act of reasoning.

### This is mostly built

Verified by running it, not by reading about it. Given a Go route renamed
`/v1/invoices/{id}` → `/v2/invoices/{id}` in `billing-service`, with the Python
consumer in `orders-service` untouched:

```bash
tracekite pr --base base-*.tracekite --head head-*.tracekite \
             --changed-repo billing-service --comment
```
```
**TraceKite**: 1 connection(s) lost across 1 repo(s). Risk: 2.85 (3 break(s)).

- **orders-service** loses `billing-service`
  - `src/billing_client.py:14`
```
```
exit code 1
```

It found a **cross-repo, cross-language, config-mediated** break that no text
search could reach — the consumer reads its host from `BILLING_URL`, set in a
compose file in a different repository — and it cited the consumer's own line.
The non-zero exit is already a CI gate. The unchanged case correctly reports
`no consumer loses a connection … Risk: 0` and exits `0`.

---

## 4. Architecture

```
  repo ──scan──▶ claims          (per-repo, independent, no cross-repo knowledge)
                   │
                   ▼
          .tracekite artifact     (SQLite, content-addressed, portable)
                   │
                   ▼
          link ── rendezvous join ──▶ edges, evidence cited on BOTH sides
                   │
     ┌─────────────┼──────────────┬───────────────┐
     ▼             ▼              ▼               ▼
    mcp           pr            drift          reverify
  (agent      (CI gate:       (declared vs    (citation rot:
   queries)    who breaks)     observed)       downgrade, never delete)
```

**The join is the product.** Claims are emitted per-artifact with no knowledge of
each other, then joined on a shared rendezvous key. That makes the edge *evidence*
rather than inference — and it is why the edges exist at all, since none of them
are present in any single source file.

### The re-derivability primitive already exists

`SnapshotIdentity.canonical_digest()`
([answer.py](../../backend/tracekite/answer.py)) hashes `{repos + revisions,
engine_version, config_version, config_digest}` and deliberately **excludes
observational timing**:

> Two answers with the same canonical digest are substantively identical.

That is exactly the receipt's identity field. An answer carrying its snapshot
digest can be re-derived and compared by anyone holding the same inputs. The
envelope around it (`AnswerEnvelope`) already carries `status`, `scope`,
`completeness`, and `freshness`.

### Cause is reported, never inferred

`impact.py` refuses to attribute a break it cannot explain:

> An edge that vanished with no source change is a regression in the tool and must
> not be served to a reviewer as somebody's fault.

This is the §1 invariant applied to the diff itself, and it is why `--changed-repo`
matters: it supplies git's knowledge, which the graph does not have. Without it the
provider's own rename is reported as a loss (risk 7.72); with it, only the genuine
consumer break is (risk 2.85).

---

## 5. Where the documents now disagree with the code

**This is the actionable section.** Three documents describe as future work things
that are already implemented. Per [AGENTS.md](../../AGENTS.md) §1, that divergence
is itself a finding.

| Document | Claims | Reality |
|---|---|---|
| `AGENTS.md` §1 | `GraphStore` is "the target, not the code"; asserting it exists "is wrong in the most expensive way" | **It is code** — `db/graph_store.py:81`, with three backends: `SQLiteGraphStore`, `Neo4jGraphStore`, `InMemoryGraphStore` |
| `db/graph_store.py` docstring | "None of them exist behind this protocol yet — B1, B2 and B3 are what implement it" | All three exist in sibling files |
| `GOAL.md` phase gates | Phase 1 *Embeddable* and Phase 4 *Change* are future work | Phase 4's exit criterion — "a PR comment names exactly who breaks" — **is met** (§3). Phase 1's — "a host scans two repos and never imports FastAPI or Neo4j" — is met by the `artifact` + `pr` flow, and `packaging/tracekite-core` exists with a measured import closure |

The irony is worth naming: the file warning that design documents drift from code
has itself drifted from the code. **These should be corrected before they mislead
an agent that was told to treat them as normative** — which is precisely what
`CLAUDE.md` instructs.

---

## 6. What is genuinely still missing

Having removed what already ships, the real remaining gap is small and specific:

1. **The receipt is not yet a first-class artifact.** `pr` computes the impact and
   prints it; it does not emit a signed, re-derivable receipt pinned to a diff, and
   nothing re-checks a stored receipt against a fresh derivation.
2. **No agent-facing write path.** The MCP surface is read-only (`services`,
   `consumers_of`, `trace`, `deprecations`). An agent cannot *submit* a claimed
   blast radius for adjudication.
3. **Scale is unproven.** `GOAL.md`'s 1,000-repo figures are extrapolated from six
   real repositories; the probe at 100 repos is the honest next step.

The distance from here to "every agent PR carries a verifiable receipt" is far
shorter than `GOAL.md` implies — most of it is packaging, not invention.

---

## 7. One defect found while verifying this

A single Go route produces **two** contract claims:

| key | framework | verdict |
|---|---|---|
| `GET:/v2/invoices/{}` | `net/http` | correct |
| `GET:/GET /v2/invoices/{}` | `gin` | **phantom** |

`go_route_extractor` is correct in isolation — run directly it returns one route,
method properly stripped. The phantom comes from the tree-sitter path:
`_framework_for_language()`
([adapter.py:658](../../backend/tracekite/parsers/tree_sitter/adapter.py)) maps
`LanguageType.GO → "gin"` as a **hardcoded per-language guess**, and that path does
not strip Go 1.22's method-in-pattern syntax (`HandleFunc("GET /path", …)`).

Consequences:

- A phantom endpoint node inflates endpoint counts.
- It inflates PR risk — 8 breaks reported where 4 are real.
- The framework label is an unverified assertion in a tool whose premise is that
  nothing is asserted without a citation.

Not yet established: whether this ever produces a false *service-to-service* edge.
It may stay an unmatched provider claim, in which case the 189 TP / 0 FP record is
untouched — but the phantom still reaches users through PR risk numbers.

