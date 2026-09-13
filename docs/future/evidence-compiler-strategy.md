# TraceKite verification and context strategy

TraceKite should build **one shared evidence foundation** for structural claim verification and economical coding-task context. Deliver the verifier first, reusing existing scan/link/PR analysis. Add an Evidence Compiler as an optional adapter if quality and cost experiments justify it. Both uses must expose missing and outdated evidence; neither establishes general runtime safety.

The most promising initial market is teams making changes across services, repositories, configuration and API boundaries. These are the places where an agent can spend many turns reconstructing a connection that TraceKite can already derive mechanically. A one-file edit is a useful control case, not the main reason to adopt this product.

### The recommended bet

For the optional compiler, prototype the **Rendezvous Witness Compiler**, or RWC, over shared analysis receipts. A witness is the provider, consumer and configuration evidence supporting a connection. Selection must preserve these witnesses, track unresolved questions, and watch inputs that could change an answer, including previously unseen consumers. RWC is not a second graph or verification engine.

The intended developer experience is simple. The agent receives the relevant contracts and source locations, an explanation of what remains unknown, and a way to expand exact source. After a code or configuration change, it receives a replacement packet whose validity can be checked. Repeated questions can reuse computation without making yesterday's answer look current.

**The research hypothesis is specific:** on supported cross-repository change tasks, witness-aware selection plus dependency-aware revalidation can lower dollars per accepted task relative to a well-tuned search or retrieval baseline, without an unacceptable loss of task success. This is a proposed experiment, not a measured TraceKite result.

### What would make this important

The larger opportunity is to make codebase understanding reusable infrastructure. A team should not need every coding agent to rediscover the same service bindings. Verified source facts can be shared within an authorized snapshot; model-generated reasoning and unverified conclusions should not become shared truth. If the evidence layer is useful across models, changing an agent or model should not require rebuilding that layer.

For the compiler, target at least **30 percent lower cost per accepted task** against a baseline with the same verification policy. Require a predeclared quality margin and publish failures. Measure the verifier's correctness and review value separately. Smaller serialized responses alone do not establish either product benefit.

### Novelty and open source

Graphs, prompt compression, context compilers, proof-carrying packets and incremental caches already have prior art. Neither the product name nor the combination alone establishes a new algorithm. RWC is a candidate contribution that needs a precise specification, a comparative implementation and reproducible results. There is no basis here for a worldwide-first or patentability claim.

An open-source advantage must survive inspection. Keep the kernel, receipt validator and benchmark public. Build defensibility through cross-repository coverage, integration quality, difficult regression fixtures and measured economics. A hidden ranking formula would provide a weaker foundation for trust.

<!-- page -->

## Verification and context compilation

The [agent verification design](../design/agent-verification-layer.md) defines the proposed shared receipt contract and verification boundary. This strategy covers optional context selection and its economics. Keep both documents as views of one plan, not specifications for separate evidence systems.

| Dimension | Verification layer | Evidence Compiler |
| --- | --- | --- |
| Main question | Does a stated structural claim agree with scoped evidence? | Which evidence should the coding task receive within its budget? |
| Typical use | CI or review after an edit; also pre-edit assertions | Preparing and refreshing context during a task |
| Existing foundation | Scan, link, base/head PR impact, drift and answer contracts | The same engine, graph queries and answer envelope |
| New work | Trusted input scope, claim comparison, stored-receipt replay and explicit verdicts | Witness selection, token accounting, source expansion and session lifecycle |
| Success evidence | Correct scoped verdicts, useful counterexamples, review effort | Cost per accepted task and quality relative to the same verifier without a compiler |
| Release dependency | Can release without context compilation | Requires shared evidence primitives, not CI posting or signing |

The shared foundation owns source and artifact identity, query/diff identity, derivations, completeness and replay. A context packet references its receipts and adds presentation policy; it must not create competing definitions of truth, freshness or evidence. The current PR command already analyzes losses, but it does not yet verify an agent claim or replay a first-class receipt.

A snapshot hash is not an answer hash. Base/head scope, query parameters, analysis limits, configuration and engine identity must be bound separately. A token budget may shorten presentation but must not silently remove a contradiction from adjudication. A signed receipt authenticates its issuer, not its semantic correctness.

Deliver the shared RWC-02/03/06 work and the verification-specific AV-01/02 adapters first. Run the RWC-01 baseline alongside them. Use full replay initially; selective invalidation and context ranking are not required for an honest verifier. If only one new capability can be funded, choose verification and leave the compiler gated on evaluation.

This changes the earlier compiler-first sequencing. It preserves the cost-reduction research direction while recognizing that PR analysis already exists and that both branches need the same dependable inputs. Existing task statuses and public APIs are unchanged by this plan.

<!-- page -->

## Token economics and the actual objective

Measure **all spending divided by accepted tasks** over a fixed evaluation cohort. Include failed and abandoned attempts, repeated prompts, cache writes, cache reads, output and billable reasoning, tool fees, and amortized indexing and revalidation. Report human review time separately. If no tasks are accepted, the cost per accepted task is undefined; reporting zero would conceal failure.

Prices vary by model and token category. Anthropic's current Sonnet 5 prices, per million tokens, are $2 for base input, $10 for output, $0.20 for cache reads and $2.50 for five-minute cache writes. Those are the rates used below, checked September 13 2026. They are one provider example, not a recommendation or a permanent price assumption.[^pricing]

### Illustrative economics rather than a benchmark

The volumes in this table are hypothetical totals per attempted task, summed across its model calls. The four token categories are disjoint. Costs assume standard first-party rates without taxes, negotiated discounts, residency premiums or batch discounts.

| Cost component | Baseline volume | Proposed volume | Baseline USD | Proposed USD |
| --- | --- | --- | --- | --- |
| Uncached input | 400000 tokens | 160000 tokens | 0.80 | 0.32 |
| Cache reads | 1600000 tokens | 800000 tokens | 0.32 | 0.16 |
| Five minute cache writes | 100000 tokens | 80000 tokens | 0.25 | 0.20 |
| Output including billable reasoning | 80000 tokens | 60000 tokens | 0.80 | 0.60 |
| Tools and amortized local work | Assumed | Assumed | 0.08 | 0.10 |
| Total per attempt | | | 2.25 | 1.38 |

At an assumed 80 accepted tasks out of 100 attempts in both arms, the totals would be $225 versus $138, or $2.81 versus $1.73 per accepted task. That is a 38.7 percent reduction. This calculation demonstrates the measurement method; none of these task volumes or success rates has been observed for RWC.

### The savings trap

Removing 800000 cached input tokens at the example rate saves only $0.16. Adding $0.10 of indexing cost and 10000 extra output tokens costs $0.20. The supposedly leaner system is then $0.04 more expensive. A pruner that causes another planning or repair loop can erase its input savings.

Provider prompt caching and TraceKite artifact caching solve different problems. Anthropic documents exact prefix matching, cache isolation and separate output generation. A cached TraceKite packet does not make its text free to send to a model, and a shorter tool result does not remove earlier conversation history.[^caching]

For seat-based subscriptions, reduced token use may improve limits or throughput without lowering the invoice. The product must report observed provider usage and actual billing terms rather than translate every omitted byte into claimed customer savings.

<!-- page -->

## Existing approaches and competitive implications

The context layer is already competitive. The following are documented capabilities or author-reported research results, not independently reproduced comparisons. Public product descriptions do not establish what a competitor lacks internally.

| Approach | Existing work | Implication for TraceKite |
| --- | --- | --- |
| Budgeted repository maps | Aider ranks a file dependency graph and selects content under a token budget.[^aider] | Graph ranking under a budget is a baseline, not the invention. |
| Symbol level tools | Serena offers semantic retrieval and editing through MCP.[^serena] | Exact symbol access should be reused or interoperable, not rebuilt for differentiation alone. |
| Live cross repository retrieval | Augment documents relationship-aware context and local or remote MCP integration.[^augment] | Cross-repository context and model-neutral access are already marketed. |
| Learned context pruning | SWE-Pruner reports task-aware line selection; SWE-Pruner Pro uses an agent's internal representations.[^pruner] | Neural pruning is a serious comparison arm, with its own inference and integration costs. |
| Semantic and structural selection | LaMR separately models semantic evidence and dependency support.[^lamr] | Combining relevance with dependency support is also prior art. |

SWE-Pruner reports 23–54 percent token reduction on its evaluated agent tasks. SWE-Pruner Pro reports savings up to 39 percent across its tested settings and relies on access to open-weight model internals. These are workload-specific author results; they do not imply equivalent invoice savings for TraceKite or applicability inside a closed model API.

LaMR's dependency-support mechanism is particularly relevant to RWC. A comparison should ask whether explicitly retained derivations and invalidation guards add value beyond a learned selector that already considers code structure. Calling all competing tools similarity-only systems would be inaccurate.

The initial implementation should therefore avoid training another compressor. First test whether TraceKite's existing source evidence can remove repeated discovery work. A learned selector is a later experiment only if a simple deterministic policy leaves a measurable opportunity.

<!-- page -->

## Closest prior art and the proposed contribution

Several public projects already describe much of the proposed product vocabulary. Qarinah documents proof-carrying task packets with hashes, citations, selection reasons, budgets and temporal status. Its documentation explicitly distinguishes inspectable selection from proof of truth or task correctness.[^qarinah]

Grape documents dependency-tracked context artifacts, session-aware deltas, restoration and stale-context invalidation. Its current contract distinguishes exact-source proof from behavioral correctness and records incomplete retrieval. These capabilities overlap directly with a generic proposal for reusable context packets.[^grape]

ContextOS describes compiled context as a materialized view of supported, missing, conflicting and omitted evidence, including decision obligations. This is direct conceptual prior art for obligation-aware context compilation, not a distant analogy.[^contextos]

Incremental reasoning also has established precedents. CodePlan combines dependency analysis, change-impact analysis and adaptive edit planning. Bazel shares content-addressed action results, while counterexample-guided abstraction refinement long predates coding agents.[^foundations]

### The contribution worth investigating

RWC should focus on a specific technical problem: **maintaining a budgeted explanation of supported cross-repository queries when the matching evidence can change outside the files previously returned**. Its domain is TraceKite's rendezvous joins across source and configuration, not arbitrary agent memory.

The proposed design couples three mechanisms. It selects whole evidence bundles for declared questions. It records the candidate sets and configuration inputs whose changes could invalidate an answer. It replaces affected answers atomically while retaining unresolved and omitted obligations. Each mechanism must also be evaluated separately so a result does not hide behind a large system.

The most revealing case is a newly added consumer. A cache watching only the old returned files can miss it. A cache keyed to the entire estate can detect it but discard too much work. RWC would track the relevant matching predicates and their generations, falling back to wider invalidation whenever those dependencies cannot be enumerated soundly.

This is a **systems research hypothesis**, not a demonstrated new theorem. Query dependency tracking, set-cover-style selection and provenance are established building blocks. The useful claim to establish is a measured cost and correctness advantage for their carefully bounded application to cross-repository code changes.

### Bound the promise

A receipt can establish that a result follows from a named snapshot under named rules. It cannot establish that an absent runtime dependency does not exist, that source text is trustworthy, or that the agent's patch is correct. Google Research's sufficient-context work also distinguishes relevant material from material that actually supports an answer; relevance alone is not a completion criterion.[^sufficient]

<!-- page -->

## Current TraceKite foundation and architecture

The current source provides useful foundations. `AnswerEnvelope` carries status, snapshot, scope, completeness and freshness. The facade loads a graph once and answers from memory. The CLI already compares base/head artifacts through `pr`; that analysis is reused by the proposed verifier. Neither a first-class receipt verifier nor RWC is established by those primitives alone.[^local]

The reviewed facade and MCP wrapper set freshness to `UNKNOWN`. The existing re-verification heuristic checks for a claim token near a cited line; it does not validate the complete provider, consumer and configuration derivation. Treat that diagnostic as a diagnostic. A changed method or binding can invalidate a relationship while leaving a familiar token in place.

Snapshot identity is also not answer identity. Two different queries over the same snapshot can have different answers. A reusable answer key must additionally include canonical query parameters, scope, filters, limits and relevant policy. A rendered packet has another identity that includes its budget, representation policy and tokenizer version.

| Layer | Responsibility in the proposal | Boundary |
| --- | --- | --- |
| Existing deterministic engine | Claims, joins, typed graph answers and base/head impact | Never let an LLM invent an authoritative edge. |
| Shared receipt and query services | Evidence bundles, scoped verdicts, replay and dependency manifests | One implementation for verifier and compiler; explicit inputs only. |
| Storage and boundary adapters | Snapshot capture, refresh, content reads and atomic publication | Reuse existing ports and artifact storage. |
| Optional agent adapter | Task interpretation, context selection, model calls and usage accounting | Keep retrieval/ranking policy outside the normative core scope. |

The architecture and GOAL documents place general retrieval, ranking and agent decisions in hosts. Preserve that boundary: the pure engine produces evidence and query dependencies; a separately packaged adapter decides what to present to a model. Any decision to move general agent planning into core requires an explicit architecture change.

### Immediate engineering opportunities

The MCP compatibility wrapper retains legacy result fields at the top level and includes them again under `result`. A negotiated compact response format could avoid duplication for new clients while preserving all warnings and source references. Measure this as a small optimization; it is not the central algorithm and must not break existing consumers.

Before claiming current-source guarantees, add a coherent snapshot capture and revalidation boundary. File reads, metadata collection and source changes must not race into a mixed packet. Repository-qualified source identity must survive joins and serialization, including two repositories with identical relative paths.

The existing release plan already contains receipts, bounded packs, incremental invalidation and optional host selection. Extend CTX-005, CTX-006, CTX-007, INT-004 and CTX-012 rather than create a competing implementation. An earlier contract check passed 41 tests across answer, facade and completeness tests; this is not an agent-cost or runtime-accuracy benchmark.

<!-- page -->

## Algorithm inputs and evidence obligations

RWC receives a typed request, immutable snapshot, explicit repository scope, host policy and context budget. The host interprets the task. Model-selected targets remain candidates until exact resolution succeeds; ambiguity remains an answer state.

An **obligation** is a question the packet must address, not a prediction about everything needed to solve the task. For an endpoint migration, a reviewed template can require the current provider contract, observed consumers, the configuration chain, relevant coverage gaps and exact source for the intended edit. Runtime compatibility and final test acceptance remain separate obligations owned by the host.

| Obligation | Acceptable evidence | What does not satisfy it |
| --- | --- | --- |
| Identify the provider | Current canonical identity plus source citation | A guessed service name |
| List observed consumers | Supported query result with scope and truncation | An empty list without coverage information |
| Explain a connection | Consumer, provider and binding derivation | A nearby import or a confidence score alone |
| Inspect the edit target | Current exact source at an authorized span | A signature or generated summary alone |
| Validate the change | Named checks against the exact candidate revision | Presence of a test file or an agent saying done |

### Evidence as bundles

Represent derivations as a directed acyclic graph of facts and their supporting inputs. A cross-repository connection may require several premises together; model that as a bundle rather than rank each line independently. If a required configuration premise disappears, that particular derivation no longer supports the assertion.

Deduplicate shared premises. Ten consumers may share one gateway rule, so the packet need not repeat the rule ten times. Preserve alternative derivations where the resolver actually supports them. Do not turn ambiguity into a chosen provider, and do not remove a connection simply because one of several valid derivations changed.

Each obligation has an explicit result state such as `supported`, `known_empty_in_scope`, `ambiguous`, `unavailable` or `needs_more_evidence`. The adapter must also represent `budget_exceeded` and `omitted`. An unresolved mandatory obligation can be displayed truthfully, but it does not become satisfied because its warning fits inside the prompt.

### A limited correctness target

For supported typed queries, require every asserted result and its status to agree with the canonical query on the pinned snapshot. A validator checks derivation dependencies and source identities. Agreement with the same parser is not independent semantic validation: a reproducible extraction error can pass this check. The target concerns the represented query result, not completeness of program behavior or sufficiency for an arbitrary coding task.

No finite graph certifies that all omitted code is irrelevant to arbitrary tasks. Unsupported patterns, dynamic dispatch, runtime discovery, missing repositories and hidden configuration remain explicit. High-risk changes require broader inspection or review; a packet does not authorize action.

<!-- page -->

## Budgeted witness selection and refinement

Reject budgets below the protocol's minimum envelope size. Reserve space for identity, scope, statuses, freshness and omissions before selecting optional content. Pin applicable trusted instructions and exact edit-target source according to host policy. Count the complete serialized payload with a versioned model tokenizer where available; otherwise label the estimate and keep a conservative margin.

The initial selector should be deterministic. Use a reviewed task template to assign obligation priorities, then choose evidence bundles by the additional obligations they address per additional serialized token. Shared evidence is charged once. Confidence may be exposed with its statistical basis, but must not be multiplied into a fictitious per-fact probability of truth.

```text
compile(request, snapshot, policy, budget):
    obligations = instantiate_reviewed_template(request, policy)
    answers, witnesses, guards = query_engine(snapshot, obligations)
    packet = mandatory_identity_status_and_gap_fields(answers)
    pin_required_source_and_rules(packet, policy)
    if measured_tokens(packet) > budget:
        return budget_exceeded_with_required_size()
    while an unselected bundle with positive obligation gain fits:
        bundle = best_marginal_obligation_value_per_token()
        add_bundle_and_all_required_premises(packet, bundle)
    packet = fit_with_omissions_and_support_closure(packet, budget)
    return validate_or_budget_error(packet, witnesses, guards)
```

This is a constrained, set-cover-style heuristic, not a claim of globally minimum context. Use canonical tie-breaking and a bounded candidate pool. Finalization serializes omissions and supporting metadata, recounts tokens, then removes an optional bundle and recomputes support closure and omissions until the packet fits. Each iteration removes a bundle, so it terminates. If mandatory content and omission metadata alone exceed the budget, return an explicit budget error. Never drop a premise still required by a retained claim.

### Progressive source disclosure

Allow four representations: a navigation index, a typed fact with citations, the exact supporting excerpt, and the surrounding source needed to edit. Structural questions may be answered by typed facts. Behavioral changes usually require implementation bodies and applicable surrounding constraints. A generated summary is never a substitute for exact source at a protected edit site.

If an agent requests a missing body, a verifier finds a stale premise, or a test failure identifies a new relevant location, the adapter opens a specific obligation and recompiles. A diagnostic location is evidence for further inspection, not proof of root cause. An LLM can propose a new question but cannot promote its own answer into the authoritative graph.

### Stop conditions

Return an explicit incomplete result when the required context cannot fit, the scope cannot be resolved, or the retrieval allowance is exhausted. The host may approve a larger budget, widen the search, or stop. The compiler must not buy a better completion rate by silently exceeding the budget.

Begin without an LLM in the compilation path. Later experiments may estimate the value of another retrieval, but must charge the estimator's own cost and keep hard evidence requirements intact. Learning belongs in a versioned adapter policy, not inside deterministic edge creation.

<!-- page -->

## Incremental revalidation and newly appearing evidence

The difficult cache problem is not detecting a changed returned file. It is detecting a change that creates a new answer. Suppose a packet lists two consumers of a contract. A third repository later adds a consumer. None of the two old call sites changed, yet the previous result set is no longer current.

RWC should record both its **read dependencies** and its **matching dependencies**. Read dependencies identify exact claims, source content and configuration premises. Matching dependencies identify the query predicates and candidate sets that could add, remove or disambiguate results. Watching a currently empty candidate set is essential when absence or uniqueness influenced the answer.

### A candidate manifest

The manifest should bind the query, expected repository inventory, snapshot, parser/resolver versions, configuration identity and authorization scope. Record the rendezvous buckets, alias/gateway inputs, coverage and generations of consulted sets. Packet selection also depends on unselected candidates: changes to their ranking inputs, selection policy or tokenizer must trigger reselection even if already returned facts remain valid.

On a source update, compute changed facts and changed matching sets, then invalidate their dependent answers. An unrelated README edit can leave a particular relationship answer reusable. A new call site in a watched bucket must invalidate the consumer list. A new repository must invalidate an estate-wide inventory assumption even if no old artifact changed.

### Conservative handling of difficult queries

Exact-key watches are insufficient for prefix routing, wildcard matching, alias changes and environment substitution. Those operations need dependency tracking for their actual query predicates or a wider namespace/configuration generation. When dependency tracking is incomplete, invalidate the whole affected query or snapshot. Correct coarse invalidation is preferable to selective reuse that misses a new match.

If a dependency changes, re-run the relevant query. The output may remain identical because an alternative witness still supports it. A generation change is a reason to revalidate, not proof that the relationship disappeared. Large configuration changes may require broad recomputation; no sublinear worst-case guarantee is proposed.

### Atomic replacement

Parse captured immutable bytes and bind their digests to the artifact; never hash one version and parse another. Claim a coherent working-tree snapshot only with an actual filesystem snapshot, a cooperating writer lock, or reliable monotonic change generations. A before/after hash comparison can miss an edit-and-revert cycle. Without coherence evidence, report unverifiable. Publish one explicitly identified repository revision vector per packet.

A host session uses a base packet ID and an epoch to apply replacements. Missing base packets, branch changes, compaction or session resets require rehydration. A receipt stored on disk does not imply its contents are still visible to the model. Reuse validated result bodies under a new envelope when the snapshot changes; never relabel or overwrite an immutable old receipt. Publication, cache eviction, authorization changes and read failures all need explicit behavior.

Under the stated dependency-tracking assumptions, unchanged guards permit reuse of that typed query's result. This is the proposed invariant to test. It is not a guarantee about the entire program, and it is not satisfied by hashes of the previously selected excerpts alone.

<!-- page -->

## Example of an endpoint migration

Consider an illustrative estate with an orders service, a web application, a billing worker and a gateway configuration repository. The task is to migrate callers from `/v1/orders/{id}` to `/v2/orders/{id}`. The identifiers and paths in this example are invented to explain the proposed interface; they do not describe the current TraceKite checkout.

The provider route alone is insufficient. The web application may call a gateway prefix, and the worker may obtain its host from configuration. TraceKite's supported joins should establish the connections before the model attempts to reason about which source to change. A runtime-discovered client remains a coverage gap unless separately observed.

| Stage | Packet content | Required agent behavior |
| --- | --- | --- |
| Initial query | Provider, observed call sites, binding chain and gaps | Inspect exact edit targets; do not claim all runtime clients are known. |
| Working edit | Current source plus the explicit migration request | Make the authorized patch in the host workspace. |
| Revalidation | Changed query results and any stale premises | Reinspect affected bindings before relying on the old packet. |
| Concurrent new client | Invalidated result set and refreshed consumer list | Include the new known client or explain why scope excludes it. |
| Acceptance | Test results bound to the candidate revision | Report what passed and what remains unverified. |

### Proposed packet shape

```json
{
  "packet_version": "experimental-1", "snapshot_id": "snapshot-A",
  "analysis_receipt_ref": "receipt-A", "status": "needs_more_evidence",
  "facts": [{"id": "F1", "witness_ref": "W1"}],
  "open_obligations": ["runtime_client_inventory"],
  "omitted": [], "refresh_guard_ref": "G1",
  "context_budget": {"limit": 4000, "tokenizer": "pinned"}
}
```

This abbreviated example is not a released API. Real facts must include repository-qualified source locations and derivation metadata; opaque IDs are useful only when the host can resolve them. The agent sees the relevant fact and citations, while a validator can load the full receipt. Editing still requires source text.

### Where the intelligence comes from

The compiler removes mechanical discovery work: joining host bindings, locating known consumers and finding which assumptions moved. The model supplies task interpretation and code changes. Tests and reviewers determine acceptance. Keeping those roles separate makes it possible to measure whether the evidence layer helped.

The demonstration must include a failing case. Add a new consumer without touching any previously selected file, then show the old answer being invalidated. Also remove access to one repository and show an incomplete result rather than a confident disappearance of its consumers. These are stronger demonstrations of dependability than a small prompt alone.

<!-- page -->

## Agent integration and trust boundaries

A useful algorithm still needs control over the right integration boundary. MCP makes a tool available; it does not ensure an agent calls it, removes old history, follows omissions or changes its provider billing behavior. The first integration should be a host where TraceKite can observe actual requests, tool use and usage receipts.

| Integration mode | Realistic control | Claim to measure |
| --- | --- | --- |
| Advisory MCP | Typed tools and bounded self-contained responses | Less discovery work when the agent uses the tool |
| Managed host adapter | Context assembly, refresh, rehydration and budget accounting | Lower end-to-end cost at the required task quality |
| Authorized team service | Shared immutable artifacts and query computation | Amortized indexing and fewer repeated analyses |

Keep the existing four primitives usable. Proposed experimental adapter operations can be `prepare_context`, `expand_evidence`, `refresh_context` and `record_validation`. Record validation accepts only host-observed results with a revision and command identity; a model-written claim that tests passed is not equivalent evidence.

### Source and access safety

Treat retrieved code, comments and documentation as untrusted data, even when content-addressed. A digest establishes identity, not author authenticity or freedom from prompt injection. Keep trusted host policy outside retrieved source, and do not allow source comments to grant tools or expand filesystem access.

Every excerpt read must obey allowed roots, repository identity and authorization. Apply redaction before source leaves the machine. Include access policy in cache partitions and recheck it on reads; a previously authorized receipt must not leak a repository after access is revoked. Shared telemetry should contain only approved metadata, not source, secrets or model reasoning.

Dirty worktrees, branches and environment configurations are distinct states. Share immutable facts only across compatible states and authorized users. Keep private working-copy evidence local by default. Bound disk use and give artifacts a retention policy without misrepresenting eviction as a source change.

### Compatibility and honest accounting

Use version negotiation for compact responses. Never remove scope, stale-state or omission information to reach a marketing token target. Add protocol tests for unknown fields, incompatible versions, restoration failures and clients that ignore refresh instructions.

A managed adapter can evaluate cache-friendly ordering of stable context and changing context. It must preserve the host's required conversation and tool-result semantics. An advisory plugin must not claim that sending a delta erases previously billed tokens. Both modes should allow users to inspect the packet and request original source.

Do not build a new autonomous coding agent as the first product. The initial deliverable is an evidence layer and one instrumented adapter. Model routing, autonomous test selection and broad long-term memory are separate experiments whose savings and failure modes must be measured independently.

<!-- page -->

## Evaluation design and release criteria

Measure dollars per accepted task over all attempts. Define acceptance with held-out tests and a task-specific review rubric before running agents. Also report resolve rate, review time, unsupported assertions, citation validity, stale answers, omitted required evidence, wall time and indexing/storage costs.

### Comparison arms

Use identical tasks, models, access and budgets. Compare tuned search/caching A, current TraceKite tools B, and B plus RWC C. Apply the same verifier and acceptance policy to all arms and count its costs. C versus B isolates the compiler's value. Include an external context baseline where feasible; otherwise limit the claim.

Test mechanisms separately: remove witness bundling; use full-snapshot invalidation; remove progressive expansion; and disable compact encoding. Evaluate small-model routing only after establishing same-model benefits.

### Workload and leakage controls

Include single-file fixes, cross-repository API/configuration changes, library upgrades, new consumers, alternative providers, unsupported patterns, dirty trees and high-degree graphs. Hold out repositories and change families. Keep reference patches and hidden tests out of agent context.

Public benchmarks do not establish cross-repository benefits by themselves. Compare with RepoGraph where applicable. A recent SWE-Bench Pro Verified preprint reports leakage and task-quality problems; audit environments and keep evaluation material inaccessible to agents.[^benchmarks]

### Staged spending

Start with offline fixtures, then a 20-run check: ten tasks, one host, two arms. If viable, 30 tasks with two hosts, three arms and two repetitions require 360 runs. At an assumed $2–$10 per run, the pilot costs $720–$3600 before setup and review. No paid runs are authorized here.

### Predeclared acceptance gates

- Target at least 30 percent lower cost per accepted task, with uncertainty reported. A confirmatory interval for the cost ratio must exclude no improvement; do not cherry-pick a favorable subgroup as the overall result.
- Require the one-sided 95 percent lower confidence bound for the success-rate difference to exceed a predeclared minus 2 percentage-point margin. The pilot is for sizing the confirmatory study, not proof of this narrow margin.
- Require zero unsupported deletion permissions, cross-tenant disclosures and missed invalidations on the curated adversarial suite. This is a finite-suite requirement, not a universal safety guarantee.
- Report repeated runs and repository-clustered uncertainty. If the sample cannot establish non-inferiority, call the result inconclusive. Publish failure examples and cold-cache results alongside warm-cache results.

Stop or narrow the effort if retries erase savings, consumers ignore the tools, metadata dominates small tasks, or coverage gaps prevent useful cross-repository answers. Prefer a small effective tool over a broad unsupported claim.

<!-- page -->

## Implementation tasks and sequencing

The following are proposed document-local task IDs. They are not new entries or status changes in `tasks.csv`. They extend the existing intelligence roadmap and should be reconciled into that tracker before implementation. Scheduling assumes a small team; acceptance evidence, not a calendar date, controls progression.

| ID | Deliverable and dependency | Acceptance evidence |
| --- | --- | --- |
| RWC-01 | Quality and cost baseline. Extend REL-008. | Separate verifier review value from compiler economics; count failed attempts and verification costs. |
| RWC-02 | Coherent snapshots and exact source identity. Extend CTX-005 and CTX-006. | Dirty-tree, concurrent-write, edit-and-revert and duplicate-path fixtures cannot yield falsely current receipts. |
| RWC-03 | Shared receipts, typed analysis and replay. After 02; extend CTX-005/006 and INT-002. | Query/diff identity is explicit; witnesses and gaps survive replay; no duplicate verifier. |
| RWC-04 | Query guards and conservative fallback. After 03; extend INT-004. | New consumers, alias/config changes and changed unselected ranking inputs trigger the required refresh. |
| RWC-05 | Deterministic packet selector. After 03; extend CTX-007 and CTX-012. | Final budgets include omissions; trimming preserves support closure and terminates or reports overflow. |
| RWC-06 | Versioned receipt interfaces and compact encoding. After 03; extend INT-003. | Legacy readers work; new interfaces preserve verdicts, witnesses and warnings. |
| RWC-07 | Refresh, restore and atomic replacement. After 04 and 05. | Branch changes, missing bases, compaction and access revocation behave correctly. |
| RWC-08 | One managed host integration. After 01, 06 and 07. | Real model requests, context state and usage receipts are observable; source remains recoverable. |
| RWC-09 | Paired pilot and independent acceptance. After 08; extend REL-008. | Complete paired outcomes, cost accounting, drift fixtures and failure taxonomy are published. |
| RWC-10 | Compiler release decision and second host. After 09. | Confirmatory evidence supports the compiler workload; install, compatibility and security gates pass. |

### The first milestone

Build shared RWC-02/03/06 and verification-specific AV-01/02 first, with RWC-01 measurement alongside. AV-01 compares explicit claims using trusted scope; AV-02 integrates CI policy and adversarial evaluation. Their detailed acceptance lives in the verification design. Full replay is sufficient for the first verifier; optional RWC-04/05/07/08 follows later.

Do not train a model or build a hosted fleet during this milestone. A verifier may release independently after its correctness and integration gates. The compiler's later ten-task check tests same-model benefit against that foundation. Preserve ordinary source inspection when evidence is insufficient.

### Engineering constraints

Keep new modules within the repository's 300-line production limit and respect downward dependency rules. Do not add a second parser, canonicalizer or graph engine behind the adapter. Preserve user work, run contract and layer checks, and re-ingest before stored-graph accuracy evaluation when extraction or linking changes. Separate source, tests, installation, live agent behavior and release evidence.

<!-- page -->

## Open source strategy and long term advantage

The recommended initial user is a platform or developer-productivity team supporting agents across several services. Start with contract migrations and configuration-dependent changes because their evidence can cross repository boundaries and their outcomes can be tested. Broaden only after the first use case produces repeatable results.

Release the deterministic kernel, packet schema, validator, local CLI/MCP adapter and benchmark fixtures openly. Source access and truthful incompleteness should not be premium features. Keep model credentials in the host and make paid remote services optional. An organization must be able to reproduce why a packet contained a fact without depending on a hosted black box.

### What can become defensible

The difficult asset is the tested mapping from real code and configuration to dependable cross-repository evidence. Build fixtures around ambiguous providers, gateway rewrites, generated clients, partial language support and new-consumer invalidation. Add regressions from opt-in user reports after removing private source and secrets. A growing suite of difficult cases is more valuable than an opaque relevance score.

A second advantage is integration reliability. Make packet inspection, source expansion, refresh and usage accounting work predictably in more than one real agent host. Measure the friction of installation and task setup. A powerful tool that developers must repeatedly remind an agent to call may have less economic value than a modest tool integrated at the right point.

Optional commercial services can cover access-controlled artifact distribution, fleet refresh, usage reporting, operational support and managed deployment. Prefer predictable pricing tied to managed scope or active users over a charge for every context query. Pricing and willingness to pay still need customer validation; no market-size or revenue forecast is asserted here.

### The larger research direction

If same-model savings are established, test whether cheaper models can complete the same tasks when mechanical repository investigation is handled by the evidence layer. Keep this as a separate quality–cost comparison. Small-model routing can produce a larger effect, but can also increase repair loops or missed edge cases.

Over time, multiple authorized agents could share immutable evidence computations while maintaining separate task plans and working trees. The shared object should be a recheckable fact or observed validation result, not a transcript of speculative reasoning. Learn from which obligations repeatedly require expansion, but promote new selection policies only after held-out evaluation.

### Decision

Proceed with a shared evidence foundation and scoped verification first. Test the optional compiler using new-consumer invalidation and full cost accounting. The ambition remains reusable code evidence across agents. Verification claims require their own acceptance evidence, and compiler savings require a separate controlled comparison.

Begin RWC-02/03/06 and AV-01/02 with RWC-01 measurement. A successful compiler pilot later justifies deeper selection work; a negative pilot leaves the useful verifier intact. These are stages of one product, not two competing engines or a requirement to ship both at once.

[^pricing]: Anthropic. Pricing. Live Claude Platform documentation, accessed September 13 2026. https://platform.claude.com/docs/en/about-claude/pricing
[^caching]: Anthropic. Prompt caching. Live Claude Platform documentation, accessed September 13 2026. https://platform.claude.com/docs/en/build-with-claude/prompt-caching
[^aider]: Aider project. Repository map. Live documentation, accessed September 13 2026. https://aider.chat/docs/repomap.html
[^serena]: Oraios. About Serena. Live documentation, accessed September 13 2026. https://oraios.github.io/serena/01-about/000_intro.html
[^augment]: Augment Code. Context Engine MCP. Live documentation, accessed September 13 2026. https://docs.augmentcode.com/context-services/mcp/overview
[^pruner]: Yuhang Wang and colleagues. SWE-Pruner Self-Adaptive Context Pruning for Coding Agents, January 2026, and SWE-Pruner Pro The Coder LLM Already Knows What to Prune, July 2026. Author-reported preprint results. https://arxiv.org/abs/2601.16746 https://arxiv.org/abs/2607.18213
[^lamr]: Jingjing Wang and colleagues. Context Pruning for Coding Agents via Multi-Rubric Latent Reasoning. May 14 2026. Preprint. https://arxiv.org/abs/2605.15315
[^qarinah]: Qarinah project. Proof-carrying task context. Public project documentation, accessed September 13 2026. https://github.com/AjnasNB/qarinah/blob/main/docs/PROOF-CARRYING-CONTEXT.md
[^grape]: Grape project. V1 Context Artifact. Public implementation-facing contract, accessed September 13 2026. https://github.com/gael55x/Grape/blob/main/docs/v1/contracts/context-artifact.md
[^contextos]: Piyush Kumar. Proof-Carrying Context Why AI Agents Need More Than a Context Window. ContextOS, August 28 2026. Vendor architecture article. https://contextosai.com/blog/context-proof-carrying-materialized-view
[^foundations]: Ramakrishna Bairi and colleagues. CodePlan Repository-level Coding using LLMs and Planning, 2023. Bazel project. Remote Caching, live documentation accessed September 13 2026. Edmund Clarke and colleagues. Counterexample-guided Abstraction Refinement, CAV 2000. https://arxiv.org/abs/2309.12499 https://bazel.build/remote/caching https://www.cs.cmu.edu/~emc/papers/Conference%20Papers/Counterexample-guided%20Abstraction%20Refinement.pdf
[^sufficient]: Cyrus Rashtchian and Da-Cheng Juan. Deeper insights into retrieval augmented generation The role of sufficient context. Google Research, May 14 2025. https://research.google/blog/deeper-insights-into-retrieval-augmented-generation-the-role-of-sufficient-context/
[^local]: TraceKite source baseline 7884982, reviewed September 13 2026; the verification proposal was recorded in 02c1d38. Relevant files: backend/tracekite/answer.py, facade.py, mcp_envelope.py, cli_inspect.py (cmd_pr), services/linker/impact.py, services/evidence_reverify.py and docs/design/architecture.md. The shared proposed contract is docs/design/agent-verification-layer.md. The alignment review passed 72 focused tests covering impact, CLI, packaging and answer contracts. Documentation and docstrings are corrected separately from executable behavior; the proposed verifier and compiler remain unimplemented.
[^benchmarks]: Siru Ouyang and colleagues. RepoGraph Enhancing AI Software Engineering with Repository-level Code Graph, 2024. Pujun Zheng and colleagues. SWE-Bench Pro Verified A Reliable Benchmark for Software Engineering Agents, September 8 2026. The latter is a recent preprint; its conclusions are author-reported. https://arxiv.org/abs/2410.14684 https://arxiv.org/abs/2609.08149
