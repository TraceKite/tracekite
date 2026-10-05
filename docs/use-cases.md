# What can TraceKite help me do?

[Docs](README.md) · [Feature coverage](features.md)

Choose a question, supply the repositories that could answer it, and inspect the
source citations before acting. “Indexed” below means present in those inputs
and recognized by the extractors.

## Understand an unfamiliar system

**Use:** the app's Repo and Service Map tabs.

Ingest related repositories, wait for automatic linking, and apply a shared
scope. Start with services, select one to see Calls/Called by, then search its
source in Repo. Open a module, read a node's properties, and use Back to return.

**You get:** an overview plus source locations to explore. Source-only libraries
may appear in Repo without becoming services. Follow the
[app walkthrough](quickstart.md) and [view guide](using-the-views.md).

## Find callers before changing an endpoint

**Use:** MCP/Python `search` → `node` → `consumers_of` or `impact`.

Find the exact HTTP contract or service ID, inspect its metadata, then ask for
consumers. Use `impact` for supported transitive dependency paths and a bounded
`subgraph` when you need surrounding context. Open the cited caller and provider
code. In the app, Service Map → Trace → Code (Crossings) shows supported HTTP
crossings between services.

**You get:** indexed dependents to investigate. A URL assembled only at runtime
may be absent. [Tool reference](mcp-tools.md) explains direction and limits.

## Understand frontend-to-backend connections

**Use:** multi-repository Repo view or MCP graph queries.

Load the frontend, backend, and any gateway/configuration repository. Apply the
scope in Repo. Inspect supported HTTP contract bridges; `UI_CALLS` can identify
a frontend call site. In 0.2.0, leave **Show connections only** off when inspecting
UI calls: that filter can hide a source connected only by `UI_CALLS`.

**You get:** evidence where a frontend call meets a backend contract. A relative
`/api/...` path needs enough configuration to identify its destination. The UI
bridge view is not a complete map of package, SQL, or message dependencies.

## Plan a shared-library upgrade

**Use:** [HTTP library impact](api.md#specialized-queries) or MCP/Python queries.

Ingest the publisher and consumers. Query the library's version-free package
key, such as `pkg:npm/@acme/client`, or find its `Library` node with `search`.
Inspect publishers, dependents, and recorded versions.

**You get:** indexed consumers and version differences. Private package manifests
are not automatically treated as public publishers; internal namespace
configuration and loaded publish identities control linking.

## Follow an event or data dependency

**Use:** HTTP topic-chain queries, or `neighbors` / `subgraph` around a `Topic`
or `Dataset` node.

Supply producers, consumers, schemas, and infrastructure. Resolve the topic or
dataset ID, then inspect publish/consume, fan-out, read, or write edges and their
citations. `CONSUMES_FROM` points from consumer to topic: arrow direction is not
always message-flow direction.

**You get:** supported static lineage. Identical table/topic names do not prove
shared infrastructure when scope is ambiguous. See the [graph model](graph-model.md).

## Review a pull request across repositories

**Use:** `tracekite pr` with complete base/head artifact sets.

Capture snapshots for the changed provider and unchanged consumers. Supply the
changed repo IDs and, for monorepos, changed file paths. Inspect attributed
losses, unexplained changes, and citations; run application tests alongside it.

**You get:** a review report and exit status for indexed losses. It does not
fetch arbitrary branches or post comments automatically. Follow
[change review](change-review.md) for a reproducible workflow.

## Audit configuration or a deprecation

**Use:** HTTP config ownership, CLI/MCP `deprecations`, CLI `drift` and `reverify`.

Look up an environment key's definitions/read sites, inspect deprecated contracts
and consumers, or recheck old citations against today's checkout.

**You get:** a scoped maintenance worklist. “Observed” in drift means found in
source, not captured traffic. No-consumer and dead-endpoint candidates require
manual validation before removal.

## Add graph evidence to your own developer tool

**Use:** the [Python facade](library.md) or [MCP server](plugins-and-mcp-guide.md).

Load local checkouts or artifacts, query exact identities, and show the evidence,
snapshot, coverage, and truncation with the answer. Keep your own decision,
notification, storage, and agent behavior in the host application.

**You get:** a shared scan/link engine without adopting TraceKite's web stack.
Restart or reload explicitly after source changes.
