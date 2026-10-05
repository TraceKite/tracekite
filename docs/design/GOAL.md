# Product scope and goals

[Docs](../README.md) · [Architecture](architecture.md) · [Shipped features](../features.md)

TraceKite establishes **what is connected across repositories, and how we know**.
It supplies evidence for a developer or host application to inspect. It does not
make deployment, deletion, incident-response, or agent-planning decisions.

## One engine, two deployment choices

- The local Docker app: FastAPI + Neo4j + React for ingesting and exploring an
  estate through Repo, Service Map, Trace, and the HTTP API.
- The `tracekite-core` distribution: CLI, Python facade, and MCP over local source
  or portable artifacts. Hosts use their own storage or none.

Both reuse extraction and linking. The standalone surfaces do not automatically
query the app database, and their query semantics are not all identical.

## Questions in scope

| Question | Supported approach |
|---|---|
| Which indexed components connect across these repositories? | Match source/config claims with citations |
| Why was this connection established? | Expose identity, evidence, resolver and confidence |
| Which indexed consumers might a change affect? | Dependency traversal or supplied base/head artifact comparison |
| What did the scan miss or decline? | Coverage, caps, failures, ambiguous-match counters and query limits |
| Can a host reproduce the graph? | Stable IDs, explicit inputs/configuration, deterministic artifacts |

`tracekite pr`, `drift`, and `reverify` are implemented. They are not a complete
receipt replay/agent-claim verification protocol, and a lost edge does not by
itself prove a runtime failure. The [verification design](agent-verification-layer.md)
proposes that additional layer.

## Engineering requirements

- **Precision first:** decline ambiguous signals and record the reason; never
  create a connection that cannot be supported by source evidence.
- **Determinism:** preserve stable identity and output for the same inputs.
- **Embeddability:** reusable computation must not depend on the web application.
- **One implementation:** CLI, MCP, library, and server compose the shared engine.
- **Explicit limits:** source coverage and query budgets must remain visible;
  empty results never authorize deleting or changing code.
- **Architecture invariants:** preserve the requirements in
  [architecture §6](architecture.md#6-invariants), especially bounded shared state
  and finalized matching keys.

Implementation, passing tests, measured accuracy, installation, and release
publication are separate evidence. [Historical scale records](../future/scale-measurements.md)
are workload-specific; they do not prove arbitrary estate performance.

## Future direction

Improve source coverage, refresh/invalidation, representative scale qualification,
and host integration without adding a second graph engine. The proposed
verification and optional [Evidence Compiler](../future/evidence-compiler-strategy.md)
share one evidence/receipt foundation. Verification may ship independently of a
context-selection experiment; neither makes TraceKite an autonomous action policy.

[The tracker](../../tasks.csv) records work and [CHANGELOG](../../CHANGELOG.md)
records releases. Planning phase names are not promises that all features shipped
in a similarly numbered package version.
