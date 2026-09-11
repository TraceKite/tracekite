# Developer use cases

These examples use only commands and inputs implemented by the current CLI.
All graph answers remain subject to the extraction coverage and decline
counters shipped with the result.

## Inspect one repository

```bash
tracekite scan /absolute/path/orders --repo-id orders
```

This prints claim counts, parser coverage, and explicit absence information.
It does not create cross-repository edges.

## Link related repositories

```bash
tracekite link /absolute/path/orders /absolute/path/billing \
  --now 2026-01-01T00:00:00+00:00
```

The output contains active and candidate edges, evidence, confidence, and
resolver counters. A fixed `--now` makes time-dependent output reproducible.

## Explain one edge

First copy the exact source and target IDs from `tracekite link`, then run:

```bash
tracekite explain /absolute/path/orders /absolute/path/billing \
  --edge 'SOURCE_NODE_ID' 'TARGET_NODE_ID'
```

A missing edge returns `found: false`; the command does not synthesize an
explanation.

## Publish portable artifacts

```bash
tracekite artifact /absolute/path/orders \
  --repo-id orders --head-sha "$GIT_COMMIT" --out ./artifacts
```

The command prints the content-addressed artifact path. Create one artifact per
repository.

## Review a branch across repositories

Create base and head artifacts for every repository in scope, then run:

```bash
tracekite pr \
  --base ./base/orders-<digest>.tracekite ./base/billing-<digest>.tracekite \
  --head ./head/orders-<digest>.tracekite ./head/billing-<digest>.tracekite \
  --changed-repo orders --comment
```

The base and head options take artifact lists, not git branch names. The
`--changed-repo` flag is repeatable.

## Find contract drift and live deprecations

```bash
tracekite drift ./head/orders-<digest>.tracekite \
  --base ./base/orders-<digest>.tracekite

tracekite deprecations ./head/orders-<digest>.tracekite \
  ./head/billing-<digest>.tracekite
```

Drift compares declared and observed contracts. Deprecations reports only
relationships present in the supplied artifact estate.

## Ask from an AI client

Register the stdio server as described in
[Agent and MCP integration](plugins-and-mcp-guide.md), using either source
directories or artifacts:

```bash
tracekite mcp /absolute/path/orders /absolute/path/billing
```

Useful questions map directly to tools:

- Which repository-backed services are loaded? Use `services()`.
- Who depends on this exact service or contract node? Use
  `consumers_of(node_id)`.
- Is there an active path from one exact service ID to another? Use
  `trace(from_id, to_id)`.
- Which deprecated contracts still have consumers? Use `deprecations()`.

The returned citations are navigation evidence. Open the cited source before
making a method-level claim.

## Embed the engine

The standalone core wheel is built from `packaging/tracekite-core`:

```bash
uv build --wheel --project packaging/tracekite-core --out-dir dist
```

A host can call the same pure scan and link surfaces:

```python
from tracekite import engine_config
from tracekite.db.memory_store import InMemoryLinkerStore
from tracekite.services.linker.engine import link
from tracekite.services.scan import scan

engine_config.configure(graph_hmac_key="host-owned-redaction-key")
sinks = [
    scan("/absolute/path/orders", "orders"),
    scan("/absolute/path/billing", "billing"),
]
result = link(InMemoryLinkerStore(sinks).load_claims())
```

The host owns persistence. Core does not require the HTTP server or Neo4j.

