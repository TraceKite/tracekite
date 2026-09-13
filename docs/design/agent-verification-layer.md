# TraceKite agent verification and context architecture

**Status:** unified proposal, reviewed against source at `7884982` on September
13 2026. Existing capabilities and remaining work are separated below. This
file defines the proposed shared receipt contract; [architecture.md](architecture.md)
remains normative. New APIs and verdicts below are not implemented.

## 1 Decision

Keep both use cases over **one evidence foundation**. Deliver scoped change-claim
verification first, reusing the existing scan/link/PR engine. Add the
[Evidence Compiler](../future/evidence-compiler-strategy.md) as an optional host
adapter only after its quality and cost evaluation justifies it.

| Use case | Question | Input | Output |
| --- | --- | --- | --- |
| Agent verification | Does this structural claim agree with the declared evidence? | Trusted base/head scope or a pinned query, plus an explicit claim | A scoped verdict, counterexamples and unknowns |
| Evidence Compiler | What evidence should this task receive within its context budget? | Task obligations, shared receipts and presentation budget | A context packet, citations, omissions and expansion requests |

Verification commonly runs after an edit or in CI, but it may also check a
pre-edit claim. Compilation commonly runs before and during editing. They share
analysis and source identity; neither depends on a second implementation of the
other. A compiler is not required to use or ship the verifier.

The product hypothesis is that checking structural claims can reduce review
work, while better context can reduce repeated investigation. Neither review
savings nor token savings has been measured for these proposed adapters. Tests,
source analysis and human review are complementary; none establishes all
unobserved runtime behavior.

## 2 What already exists

| Capability | Source of truth | Current limit |
| --- | --- | --- |
| Scan and link | `services/scan.py`, `services/linker/engine.py` | Extraction coverage and resolver correctness bound the graph. |
| Portable artifacts and scan reuse | `db/artifact.py`, `services/reingest.py` | Artifact reuse is not task-context lifecycle management. |
| Base/head impact and PR reports | `cli_inspect.cmd_pr`, `services/linker/impact.py` | Reports indexed losses; does not compare an agent claim or replay a stored receipt. |
| Contract drift and citation recheck | `cli_inspect.cmd_drift`, `services/evidence_reverify.py` | Token-near-line rechecks do not prove complete request/route semantics. |
| Agent queries and answer envelope | `mcp_server.py`, `facade.py`, `answer.py` | Four MCP primitives; facade/envelope freshness currently defaults to `UNKNOWN`. |
| Storage protocol and backends | `db/graph_store.py`, `sqlite_store.py`, `neo4j_graph_store.py`, `memory_store.py` | Presence of the backends does not prove every legacy storage call migrated. |
| Library packaging | `packaging/tracekite-core`, `tests/test_packaging.py` | Import/dependency checks are distinct from a clean installed-wheel test or publication. |

The existing command shape is:

```sh
tracekite pr --base base-billing.tracekite base-orders.tracekite \
  --head head-billing.tracekite head-orders.tracekite \
  --changed-repo billing-service --comment
```

The filenames above stand for real artifacts a caller must supply. The command
links each set, computes `impact`, renders a comment or JSON, and exits `1` when
`result.blocking` is nonempty. It already supplies useful CI evidence; the new
proposal must not rebuild that analysis.

Important limits established by source inspection and bounded checks:

- `--changed-repo` is supplied by the caller, not authenticated Git knowledge.
  Without it, legacy `impact()` marks losses as blocking/provider-changed.
- `cmd_pr` returns `0` when `blocking` is empty, including a tested case with an
  `unexplained` loss. Uncitable or unattributable losses can be counted without
  becoming blockers. Zero is not a completeness or safety certificate.
- Risk sums confidence over blocking edge records. Comment grouping can collapse
  multiple records into one connection. The score is not a probability, a count
  of unique runtime failures, or proof of causal breakage.
- The PR command does not bind its JSON to an agent assertion, validate the
  required estate inventory, or emit the proposed receipt manifest.

## 3 Conflicts resolved

| Earlier statement | Resolution |
| --- | --- |
| The impact receipt is mostly built | The impact engine is built. Receipt identity, replay, scope validation and claim adjudication remain new work. |
| A snapshot digest identifies an answer | It identifies declared snapshot inputs. Operation, query/diff parameters, scope and limits require additional identity. |
| Tests cannot help with impact | Tests validate exercised behavior and contracts; source evidence can identify additional dependencies to test. Neither replaces the other. |
| Determinism or provenance is unique to TraceKite | These are established techniques. Retain the compiler strategy's prior-art analysis and evaluate the implementation. |
| An agent needs a write-capable MCP path to submit a claim | A read-only adjudication operation can accept a claim as an argument without modifying the graph. |
| Receipts must be signed from the first release | Deterministic replay and authenticity are separate. A trusted CI issuer may add an optional attestation later. |
| The compiler and verifier each need their own evidence store | Share artifacts, receipt schema and replay services. Packet/session state belongs to the optional adapter. |
| Scale is only extrapolated from six repositories | Architecture §7.5 records historical 100- and 1,001-repository synthetic measurements, with claim-density caveats. Do not call them representative production-scale proof. |
| A loss proves a runtime break or a regression in TraceKite | It proves a difference in indexed results. Source/config/tool changes, missing inputs and attribution quality require separate analysis. |

The historical 189 TP / 0 FP result applies to its labeled cases. It is not a
per-fact probability or assurance against new extraction defects. The
[PetClinic examples](../future/petclinic-before-after.md) and the Go case below
show why a reproducible result can still have incorrect source semantics.

## 4 One shared foundation

```text
trusted artifact manifest and pinned analysis configuration
                         |
             existing scan link query impact
                         |
             shared receipts and replay checks
                   /                 \
      read-only claim verifier    optional context compiler
                   |                 |
             CI policy adapter    agent context adapter
```

No separate parser, join engine, provenance store or semantic validator should
be created for either branch. Persistence and source reads use existing storage
and boundary adapters. General task interpretation, context ranking, model
calls, signing credentials and merge policy remain outside the pure engine.

### Identity and contract ownership

The following are proposed records, not replacements for existing public wire
schemas. Introduce them through explicit versioning and compatibility tests.

| Record | Identity and required content |
| --- | --- |
| Input snapshot | Repository-qualified artifact and content digests, revisions, producer versions, effective config identity and completeness metadata. Unknown identity remains unknown. |
| Analysis request | Operation/schema version, query parameters or base/head vectors, expected estate inventory, filters, semantic limits and trusted change attribution. Bind resolved analysis configuration and engine/build identity. |
| Analysis receipt | Request identity plus canonical result digest, source-qualified witnesses, gaps, truncation and derivation dependencies. Observational timings stay outside semantic identity. |
| Claim check | Allowlisted predicate, explicit expected value and analysis-receipt identity, plus scoped verdict and supporting evidence. |
| Context packet | Shared receipt references, selected source/facts, omissions, tokenizer and selection-policy versions, budget and restoration metadata. It is a presentation object, not a second analysis result. |
| Optional attestation | Trusted issuer identity and signature over a receipt digest. Keep outside the semantic payload; signature validity does not prove source truth. |

`SnapshotIdentity.canonical_digest()` alone is not a cache or receipt key for an
answer. Two queries over the same snapshot may return different results. Base
and head need distinct, explicit vectors. Configuration, resolver versions,
query limits and missing input artifacts can change a comparison even when the
application source appears unchanged.

A token budget can alter the packet or displayed comment, but must not silently
alter the underlying adjudication. A capped analysis reports indeterminate
where completeness is required. A shortened presentation retains its verdict,
critical warnings and an explicit route to the omitted evidence.

Exclude only observational timings from semantic identity. If a query depends
on an analysis date or another time-valued input, that input must be pinned too.

### Claim verdicts

Start with narrow predicates such as “the indexed consumer set for this contract
is X” or “the indexed relationship losses in this base/head comparison are Y.”
Natural-language claims must be translated into this explicit form by the host.

- **Supported in scope:** the claim agrees with the canonical result and the
  claim's coverage, identity and evidence requirements are satisfied.
- **Contradicted:** a supported counterexample refutes the specified claim.
  Incomplete overall coverage need not hide a valid positive counterexample.
- **Indeterminate:** required identity, source support, input coverage, schema
  compatibility or analysis completeness is missing or conflicting.

“Safe to delete,” “all tests pass” and “nothing can break at runtime” are not
conclusions of structural graph comparison. Unsupported claim types do not
receive a supported verdict. Test outcomes need a separate host-observed
validation record tied to the candidate revision and environment.

These verdicts are separate from `AnswerEnvelope.status`: `PRESENT` only says a
query returned a result, not that an agent claim is supported. The existing
`CompletenessAssessment.safe_to_delete` remains `False`; no receipt overrides it.

Agreement with the same extractor proves reproducibility, not independent
semantic correctness. A known invalid source-to-route pairing must not be
promoted into a trusted witness merely because its hash matches.

## 5 Verification workflow

1. The trusted host chooses the candidate revision, base/head artifact inventory,
   config and required claim types. An agent cannot narrow the required estate
   or omit a required claim to manufacture a pass.
2. Validate all identities and compatibility. Treat missing artifacts, unknown
   revisions, unsupported extraction and unsafe read paths explicitly. Read only
   authorized inputs; never let a remote claim supply arbitrary filesystem paths.
   Re-derive from trusted checkouts or accept artifacts only from a producer the
   host policy trusts. A matching artifact hash does not prove that the artifact
   was produced from its claimed source revision.
3. Reuse the existing queries and PR impact engine. Capture source-qualified
   derivations and diagnostics in the shared receipt. Recompute the required
   result set rather than checking only items volunteered by the agent.
4. Compare the explicit claim. Derive changed repositories from trusted revision
   metadata; do not treat the legacy flag or risk score as verified causality.
5. Replay against the requested candidate state. A pre-edit packet is not final
   verification evidence after the code changes. Failed refresh leaves the old
   receipt historical, not current.
6. The CI adapter maps verdicts to policy. A protected check may require every
   required claim to be supported; contradicted, missing and indeterminate claims
   then block or require review. That is host policy, not a graph permission to
   merge. Posting comments and signing require separate host authority.

V1 can fully recompute pinned artifacts. Fine-grained invalidation and session
deltas are later optimizations, not prerequisites for an honest verifier.
Current `pr` exit codes remain unchanged until a separately versioned interface
is implemented. Existing MCP readers must not silently acquire write authority.

## 6 Compiler workflow and combined example

The optional compiler selects task context from the same receipts. It adds
obligation templates, exact serialized token budgets, source expansion, session
restoration and dependency-aware reuse. These are the RWC research mechanisms;
they are not another receipt verifier or another source of graph truth.

A PetClinic `/petTypes` migration illustrates both branches:

- Before editing, a packet can include the form request, gateway rewrite and
  provider route, while preserving missing-caller evidence.
- After editing, CI analyzes the pinned base/head inputs and checks the declared
  structural impact. A matching pre-edit packet or a passing unit test alone
  does not establish that claim.
- If the provider, gateway, candidate caller population or required scope moved,
  the shared dependencies require fresh analysis. Independent tests still check
  the runtime behavior of the migration.

See the pinned [before/after source examples](../future/petclinic-before-after.md).
They are illustrative workflows, not implemented RWC outcomes or savings data.

## 7 Delivery sequence and one work breakdown

Reuse the existing CTX/INT/REL roadmap. RWC IDs remain defined in the compiler
strategy; they describe a shared foundation plus optional context extensions.
The two AV IDs below are verification-only additions, not duplicate engine work.
All are proposed document-local labels; this edit does not change `tasks.csv`.

| Stage | Work | Acceptance |
| --- | --- | --- |
| A Shared foundation | RWC-01 baseline; RWC-02 input identity; RWC-03 shared receipts and replay; RWC-06 versioned interfaces | Correct scoped results, replayable inputs, explicit unknowns; no second analysis engine. |
| B Verification first | AV-01 read-only claim comparison and trusted scope checks; AV-02 CI policy integration and adversarial evaluation | Missing claims and indeterminate analyses cannot become passes; review value measured separately from token savings. |
| C Optional context experiment | RWC-04, RWC-05, RWC-07, RWC-08 and RWC-09 | Compare current TraceKite plus verifier against the same system with compiler; account for all costs and task quality. |
| D Release decisions | Existing release gates after AV-02 for the verifier; RWC-10 after RWC-09 for the compiler | A verifier release does not require the optional compiler pilot. Promote the compiler only with supporting evidence. |

AV-01 depends on the shared RWC-02/03/06 work. AV-02 depends on AV-01. The
compiler's managed integration depends on the shared foundation and its own
packet lifecycle; it does not need CI comment posting or signing to function.
A verification release must not wait for optional ranking, model routing or
selective-cache optimization.

If only one new capability can be funded, choose **verification first**. It
extends an existing PR engine with a bounded contract. The compiler remains a
separate, falsifiable cost/quality experiment. Keeping both designs is useful;
building both full surfaces immediately is not required.

## 8 Status corrections and known limitations

`GraphStore` and its three backends are implemented. The old future-tense warning
in AGENTS.md and the protocol's module docstring were stale. GOAL.md now separates
implemented primitives, historical measurements and release qualification.
Neither source packaging nor one successful example marks every phase complete.

### Go method in pattern mismatch

A bounded source check reproduced the proposed document's parsing concern on
September 13 2026. For a single `net/http` registration:

```go
mux.HandleFunc("GET /v2/invoices/{id}", handler)
```

| Path | Observed extraction |
| --- | --- |
| `services/go_route_extractor.extract_go_routes` | `GET`, `/v2/invoices/{id}`, framework `net/http` |
| `TreeSitterSourceParser.parse` | `GET`, `GET /v2/invoices/{id}`, framework `gin` |

A full scan of `corpus/billing-service` produced both HTTP claim keys
`GET:/v1/invoices/{}` and `GET:/GET /v1/invoices/{}`, both citing
`internal/routes.go:7`. The adapter retains the method in the path and maps Go to
`gin` by language. Source: [adapter.py](../../backend/tracekite/parsers/tree_sitter/adapter.py)
and [go_route_extractor.py](../../backend/tracekite/services/go_route_extractor.py).

**AV-Q01:** fix and regression-test the complete extraction pipeline before
accepting these patterns into verified claims. The duplicate/phantom claim is
reproduced; a specific risk-score inflation or false service-to-service edge was
not established by this check. Do not repeat the earlier numeric risk claims as
verified measurements. No parser behavior was changed in this documentation edit.

The stored PetClinic mismatches remain tracked as PET-RWC-01/02 in the companion
case study. Coherent snapshots and signatures cannot repair a semantic
extraction error. Those fixtures belong in both verification and compiler gates.

**AV-Q02:** preserve and test the distinction between the legacy PR exit policy
and the new verifier verdict. The adapter must inspect unexplained, uncitable,
unattributable, truncated and incomplete results instead of treating a zero exit
as approval. This is an AV-01/02 acceptance case, not another parallel project.

## 9 Evidence and validation

Primary code references: [PR command](../../backend/tracekite/cli_inspect.py),
[impact policy](../../backend/tracekite/services/linker/impact.py),
[answer contract](../../backend/tracekite/answer.py),
[storage protocol](../../backend/tracekite/db/graph_store.py),
[packaging checks](../../backend/tests/test_packaging.py), and
[historical scale measurements](architecture.md#75-measured-not-extrapolated).

The review ran 72 focused tests across `test_impact.py`, `test_cli.py`,
`test_packaging.py` and `test_answer_contract.py`. It also reproduced the Go
parser discrepancy and a CLI branch with `unexplained` nonempty and exit `0`.
These are bounded checks of existing behavior, not proof that the proposed
receipt protocol, CI adapter or context compiler has shipped. No paid agent
benchmark, production re-ingestion, registry publication or signing was performed.
