# TraceKite intelligence and open-source release plan

## Decision

Build both ideas, with a shared intelligence contract behind them. The UI should help a person explore connections and their limits. Framework integrations should receive the same analysis, evidence, scope and uncertainty in a stable machine-readable form.

The long-term product is a software intelligence engine that can answer: what depends on this, why the connection exists, what a specified change affects, which conclusions remain uncertain, and what evidence would resolve that uncertainty. A dependable integration can reproduce an answer against a named snapshot and verify it before relying on it.

This is a proposed implementation plan, not a claim that the features below already ship. Reviewed against commit `1151cc36ff74518fbfdc289809b115922f52c707`. The repository was PRIVATE when checked through GitHub during this review. The existing local Docker edit was outside this planning change.

## What the two proposals get right and wrong

| Proposal or assumption | Review finding | Decision |
|---|---|---|
| “459 loaded” means nodes | Correct. Both canvases pass `nodes.length` to the context bar. The count includes the loaded/deduplicated node pool, including bridge endpoints. | Label the unit and distinguish loaded, eligible and displayed counts. |
| All data is already available in memory | Incorrect for the full repository. The loader requests a per-repo budget and the backend returns a view-specific sample with extra context nodes. Its stats count returned nodes/links. | “Loaded nodes” is a display option. Full indexed coverage needs separate retrieval metadata and bounded expansion. |
| Swap group links for raw links | Incorrect when group IDs differ from the original endpoint IDs. | Implement a representative mapping and retain underlying relationship identities. |
| Every group-to-group count measures traffic | Incorrect. These are statically derived relationships, not observed execution frequency. | Use “relationships”; retain types and direction and show the underlying list. |
| 300 nodes is the right performance threshold | Not established by the proposal. Edge count, layout, hit testing, labels and hardware also matter. | Measure budgets. Do not silently turn “All links” into selection-only rendering. |
| MCP exposes no confidence or spans | Incorrect. `consumers_of` already returns both; `services` returns a commits map. | Preserve these fields and extend their context. |
| Ruby/PHP routing is missing | Outdated. The extraction matrix includes Rails/Sinatra and Laravel/Slim/Symfony. | Derive gap reports from current capabilities and observed failures. |
| The existing absence boolean proves no consumers exist | Too strong. It reports scan incompleteness reasons; it does not establish completeness for all frameworks, repositories, filters or runtime behavior. | Compute conservative query-relative completeness. |
| Wilson-bounded confidence is measured truth per fact | Incorrect. The implementation caps served priors using Wilson upper bounds and may retain basis `prior`. | Expose the basis, labels and limits. Do not rank by an invented truth probability. |
| Expiring receipts solve context poisoning | Too strong. The current recheck looks for a token near the cited line. A digest can also faithfully identify malicious source text. | Separate source identity, freshness, semantic support and trust boundaries. |
| Every non-edge has an attributable reason | Too strong. Counters summarize declines; the universe of absent edges is not enumerated and counters are not automatically query-specific. | Add bounded attributable diagnostics, retaining aggregate/unattributed categories. |
| These concepts have no prior art | Not defensible. Fingerprinted findings, provenance and content-addressed caching are established patterns. | Differentiate through useful cross-repo analysis, explicit limitations and measured integration outcomes. |

Current-source references: [context bar](../../frontend/src/components/GraphContextBar.tsx#L44), [2D node count](../../frontend/src/components/GraphCanvas2D.tsx#L240), [loader](../../frontend/src/hooks/useGraphDataLoader.ts#L77), [graph route](../../backend/tracekite/routes/graph.py#L14), [reader](../../backend/tracekite/services/graph_reader.py#L181), [overview mapping](../../frontend/src/lib/graphOverviewProjection.ts#L23), [MCP answers](../../backend/tracekite/mcp_server.py#L105), [capability matrix](../../backend/tracekite/services/extraction_coverage.py#L27), [absence](../../backend/tracekite/services/absence.py#L52), [reliability](../../backend/tracekite/services/linker/reliability.py#L74), [reverification](../../backend/tracekite/services/evidence_reverify.py#L43).

The live connected MCP returned a consumer with confidence 0.99 and three evidence spans during this review. Its directory-input commits map contained an empty revision. This confirms the distinction between existing evidence fields and missing snapshot context; it is not a precision measurement.

## The intelligence engine

A proposed integration facade should accept typed, bounded requests such as `explain_connection`, `assess_change`, `inspect_contract` and `investigate_missing_connection`. These are proposed interfaces, not existing callable tools. Keep the four existing MCP primitives usable.

A request supplies its scope and the question it can actually answer: node/contract IDs, repository set, source snapshot, optional base/head or an explicit hypothetical mutation, relevant environment conditions, direction, filters and limits. Arbitrary natural-language interpretation remains a host concern.

The answer contains:

- Facts and derived relationships, with origin and confidence basis.
- The source/configuration chain supporting each conclusion.
- Known affected consumers, alternatives and unresolved matching.
- Expected and analyzed repositories, source revisions/digests, engine/config version and snapshot identity.
- Coverage, omitted results, relevant declines and freshness states.
- Bounded next verification steps derived from specific missing evidence.
- Receipt references that let a host reproduce and recheck the result.

A host should be able to distinguish “known target with no observed consumers in this snapshot” from “unknown target,” “ambiguous name,” “query failed,” and “result incomplete.” None is a universal permission to delete code.

### Example integration outcome

For “What will removing this endpoint affect?”, TraceKite should identify established consumers and cite their call sites, report the provider/configuration assumptions, name missing repositories or unsupported extraction patterns, and return an explicit snapshot identifier. If the host then supplies missing configuration or a newer artifact, a refresh should produce a new answer and a reproducible delta.

“Inspect this unresolved configuration binding” is a justified next step when backed by an actual decline. “Adding Ruby support will recover 31 edges” is not justified without a controlled before/after experiment.

### Layering and scope

The pure engine computes graph facts, bounded paths, supported change comparisons, completeness assessments and hypothetical link results. Storage/boundary adapters collect files, Git metadata and artifacts. CLI, MCP and REST expose the same services. The UI renders those answers.

The existing normative scope places general retrieval, ranking, chat and incident decisions in hosts. This plan preserves that boundary. Typed investigation templates compose the graph operations that TraceKite can substantiate; they do not add a general agent planner. Optional relevance selection remains a separately evaluated host adapter.

A later refresh adapter can listen for host-supplied source changes and invalidate dependent answers. Scheduling, network access and authorization stay outside the pure engine. An immutable old snapshot can remain reproducible while being stale for the host's current working tree.

### Dependability invariants

1. Identical canonical query, source snapshot, config and engine inputs yield identical substantive answers. Observational timing stays outside their hashes.
2. Every conclusion references its supporting facts. Missing provenance remains explicit.
3. Completeness is limited to a named scope, supported extraction patterns and query limits. Empty results never become global absence guarantees.
4. A source digest binds content; it does not authenticate an author or neutralize instructions in source text.
5. A changed input invalidates affected context. Failed refresh cannot masquerade as a current answer.
6. Resource limits and omissions are returned with the answer, including when the mandatory envelope exceeds a requested budget.
7. Hosts retain control over source access, refresh and actions. Analysis performs no hidden edits or external publication.

## UI design

The current single-group drill-down is useful, but it removes the comparison context. Introduce multi-group expansion while leaving other groups visible.

Use three presentation presets: **Groups**, **Expanded groups**, and **Loaded nodes**. Keep link presentation separate: **Summary**, **Detail**, **Selected**, and **Hidden**, exposing only combinations whose semantics can be honored.

| Node presentation | Relationship presentation | Meaning |
|---|---|---|
| Groups | Summary | Directed aggregate relationships between displayed groups. Internal relationships are counted inside their group. |
| Expanded groups | Mixed summary/detail | Individual edges between visible original nodes; summaries where one or both endpoints remain collapsed. |
| Loaded nodes | Detail | Individual relationships whose endpoints are present in the eligible loaded pool. |
| Any | Selected or Hidden | A deliberate presentation choice; omitted-by-display counts remain distinguishable from missing data. |

“Groups + all raw edges” must not draw links to nonexistent original nodes. Offer to expand endpoints or show a summary inspector instead. An “Expand loaded groups” shortcut uses the same expansion machinery and respects its budget.

For every underlying node, compute one visible representative: itself or its collapsed group. Project every retained edge through this mapping while preserving its ID, direction, type and provenance membership. A summary must reconcile exactly with its deduplicated relationship list. Do not render a real node and a second synthetic copy of that same node as two entities.

Keep search and filters integrated with the same model. Distinguish searching loaded nodes from searching the repository index. A hit outside the loaded pool may trigger a bounded request for that node and its context. Preserve camera position and expansion on selection/Back; reset incompatible state when the scope changes.

### Count wording and completeness

For the pasted example, an appropriate primary label is “28 groups · 459 loaded nodes.” Also show summary-link counts with their unit. A secondary details view can report successful repos, active filters, individual relationships loaded, displayed representatives and budget omissions.

Do not show “459 of N” unless N is an authoritative total for the same scope, filters and snapshot. Unknown totals should remain unknown. Loaded-pool completeness, repository-index completeness and static-analysis capability are three different properties.

### Impact correction before expansion

A direct execution of `buildBoundedImpact` on A → B → C → D plus disconnected Z returned all five nodes from A with a budget of 80. The function has no two-hop cutoff, builds undirected adjacency and can keep unreachable nodes. The context bar nevertheless labels focused impact “2 hops.”

Fix that before denser modes make its answers more consequential. Define edge types and traversal direction explicitly; distinguish a neighborhood from reverse-dependency impact. Required regression cases include a third-hop node, disconnected nodes, cycles, excluded edge types and budget truncation. Source: [impact projection](../../frontend/src/lib/graphOverviewProjection.ts#L203).

### Rendering and accessibility

Set separate node, edge and expansion budgets from measured results, then expose operator-controlled limits through the existing configuration surface. Stable group anchors and deterministic node positions are useful options; an unmeasured universal cutoff at 300 nodes is not a requirement.

Simplifying animation may be acceptable. Silently withholding requested edges is not. When a request cannot fit, offer refinement, a relationship list or bounded export and state what was omitted. Verify keyboard access, search/list alternatives, readable labels, pan/zoom, selection and controls in normal/fullscreen 2D and 3D.

## Context proposals and sequence

| Idea | Decision | Scope and key correction |
|---|---|---|
| Meaningful absence | First release | Carry the snapshot and query limitations into all answers. Start conservatively; do not equate the existing scan boolean with universal completeness. |
| Recheckable receipts | Next milestone | Bind repo-qualified source spans, facts and derivation to immutable identities. Verify freshness against a requested revision/content state rather than assigning arbitrary wall-clock expiry. |
| Counterfactual linking | Later | Support explicit claim mutations before broadcast/normalization on a copy. Report hypothetical lost/gained links and new uncertainty, not guaranteed runtime failures. |
| Calibrated context budgeting | Deferred host experiment | Current confidence is not a truth probability. Expose statistical basis first and evaluate selection against simpler baselines. |
| Blind-spot backlog | Next milestone | Show observed affected claims/files/repos and concrete verification steps. Recovered-edge counts require an experiment. |
| Deterministic context packs | Next milestone | Export bounded typed-query answers and receipts; include all source/config/query inputs in cache identity. Reuse the existing artifact model. |
| Integration intelligence | First release, then expansion | Stable facade first; richer investigation templates and interoperability fixtures next; incremental refresh/invalidation later. |

Rechecking a receipt requires more than noticing the endpoint token still appears nearby: the provider, consumer, configuration or method semantics may have changed. The existing heuristic is a useful diagnostic but cannot serve as a complete semantic validator. Reuse it without upgrading its claims.

Repository-qualified evidence needs work at extraction/join/storage boundaries. The current MCP source explicitly notes that fused file:line strings cannot safely be assigned to one repository afterward. Receipts must preserve source identity before fusion; duplicate relative paths are a required test.

Simulations must run the normal pipeline with the same resolved configuration on copied data. Removing one provider does not necessarily remove a connection if an alternative provider remains. New candidate edges and counter deltas must stay distinguishable from supported matches. Unsupported mutations should decline.

## Research conclusions

Do not market “the only honest graph” or “nobody else does this.” The useful differentiation is the tested combination of cross-repository contract resolution, explicit query limits, reproducible context and verification that frameworks can consume.

- [GitHub SARIF support](https://docs.github.com/en/code-security/reference/code-scanning/sarif-files/sarif-support) already documents stable fingerprints, related locations and code flows. This is relevant prior art for durable evidence references, not a claim that SARIF implements TraceKite's proposed receipt protocol.
- [SLSA provenance](https://slsa.dev/spec/v1.0/terminology) separates identified inputs/outputs and provenance. Adapt the identity discipline without claiming a receipt is a security attestation.
- [Bazel remote caching](https://bazel.build/versions/7.1.0/remote/caching?hl=en) uses action hashes and content-addressed outputs. Deterministic caching is established; the opportunity is applying it correctly to scoped evidence answers.
- [Understand dependency exploration](https://docs.scitools.com/help/dependencies/browse-and-export-dependencies.html) already supports grouped architecture dependencies and directional exploration. Multi-level graph navigation is valuable UX rather than a defensible novelty claim.
- [OWASP on Memory and Context Poisoning](https://genai.owasp.org/2026/05/13/memory-is-a-feature-it-is-also-an-attack-surface/) describes persistent untrusted context as an attack surface. Freshness checks address one failure mode; they do not resolve prompt injection by themselves.
- [Evaluating AGENTS.md](https://arxiv.org/abs/2602.11988) found worse success and higher cost in its tested settings, while [On the Impact of AGENTS.md](https://arxiv.org/abs/2601.20404) reported efficiency improvements across its own sample. These are different studies and do not establish that more or less context is universally better. Evaluate TraceKite's own task outcomes.
- The pasted “5K targeted tokens beat 100K summary tokens” attribution was not verified in the primary Sourcegraph material checked here. [Sourcegraph's long-context experiment](https://sourcegraph.com/blog/towards-infinite-context-for-code) studies a different setup. Exclude the unverified number from release messaging.

## Task list and release gates

[The implementation CSV](../../tasks.csv) is the single task-status source for this plan. It contains 32 new IDs, priorities, phases, dependencies, effort sizes, rationale, implementation details, acceptance criteria and source pointers. No task is marked implemented by this review.

The older engine and coverage roadmaps are explicitly ignored by Git and record earlier work. Do not turn them into live prerequisites or change their completion statuses. New tasks extend existing seams rather than rebuilding existing scan/link, storage, calibration, PR-diff or MCP capabilities.

| Phase | Tasks | Gate |
|---|---|---|
| Public preview | 15 | Explicit counts and honest scope; corrected impact; versioned answer contract and public facade; clean install, privacy/license review and release-SHA CI. |
| v0.2 intelligence | 14 | Multi-group investigation, receipts/freshness, bounded packs, attributable gaps, richer reports and tested adapters, followed by published evaluations. |
| Later | 2 | Supported counterfactual linking and incremental answer invalidation. |
| Deferred | 1 | Optional host relevance/budget ranking, only after evidence that it helps. |

“Public preview” is a recommended feature gate, not an assertion of production readiness. Public source, a tagged release and a published registry distribution have distinct acceptance checks. The repository is currently private; making it public and publishing the package are future maintainer release actions, not actions performed by this planning change.

### Recommended implementation order

1. Begin REL-001, UX-001, UX-008 and CTX-001. They establish the contract and correct misleading current presentation.
2. Build CTX-002 → CTX-003 → INT-001 → CTX-004. Build UX-002 alongside that once the metadata contract is defined.
3. Complete REL-002/REL-003/REL-004, then REL-005/REL-006 and the explicit REL-007 public-release step.
4. Build UX-003 → UX-004 → UX-005 and CTX-005 → CTX-006 → CTX-007. Add UX-006/UX-007, CTX-008/CTX-009/CTX-011 and INT-002/INT-003.
5. Run REL-008 before claiming improved intelligence or dependable automated use. Use those results to prioritize CTX-010, INT-004 and the deferred CTX-012 experiment.

S/M/L are relative implementation sizes, not calendar commitments. Update status only with the stated acceptance evidence. The CSV dependency graph is authoritative when work can run independently.

## Verification and success

Integration evaluation should measure correct affected-consumer answers, valid source citations, unsupported safe-to-delete assertions, ability to identify missing evidence, snapshot reproducibility, freshness detection, payload size, latency and memory. Human evaluation should cover locating a caller, explaining a summary link and comparing two groups without losing context.

Use a held-out, versioned corpus with positive, empty, ambiguous, stale and incomplete cases. Compare current answers, richer answers and a direct-search baseline on identical tasks with at least two host/agent configurations. Zero unsupported safety conclusions is required on the curated failure cases; a correct decline is a valid outcome. Report sample sizes and failures rather than universal accuracy claims.

For implementation, retain the repository's required backend tests, frontend typecheck, layer/invariant/schema checks and artifact compatibility checks. Changes to extraction/linking require fresh ingestion before the stored-graph accuracy harness. Keep 2D/3D browser verification as a separate acceptance step.

Do not enlarge existing source files over 300 lines; extract a subject-specific collaborator around touched logic. The current MCP module is already near the cap, so the new snapshot, answer, receipt and query-template logic belongs in dedicated modules. Avoid a second engine behind an adapter.

## Deliverable boundary

This review creates the plan and task CSV only. It does not implement the features, alter the existing Docker configuration, publish packages, change GitHub visibility or issue announcements.
