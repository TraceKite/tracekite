# Read a graph answer

[Docs](README.md) · Related: [Graph model](graph-model.md)

An edge says that TraceKite found supporting source evidence in the inputs it
analyzed. It does not say that a call happened in production or that the scan
found every possible connection.

## Four things to check

1. **Identity:** is this the repository, node, or service you meant? Use exact
   IDs from search/service results when names are ambiguous.
2. **Evidence:** open each cited file and line at the recorded revision. Inspect
   the call, configuration, and provider that explain the connection.
3. **Scope:** were all relevant repositories supplied? Is the query limited by
   hops, filters, node/edge budgets, or the UI's loaded sample?
4. **Coverage and freshness:** check parse failures, skipped inputs, declines,
   source revisions, and whether the graph has been refreshed.

## MCP and Python answer envelopes

Every MCP tool and facade query returns these fields. MCP puts the JSON inside
`result.content[0].text`; Python returns an `AnswerEnvelope` object.

| Field | What it tells you |
|---|---|
| `answer_version` | Version of this response contract |
| `status` | Whether a result exists or why the query could not resolve it |
| `result` | Tool-specific data: services, nodes, edges, consumers, or paths |
| `snapshot` | Input repository revisions and engine/config identity |
| `scope` | Query parameters, repositories, and `truncation` |
| `completeness` | Scan completion, missing repos, parse failures, coverage reasons |
| `freshness` | Currently `unknown` in MCP/facade; no automatic source watcher |
| `candidates`, `reason` | Disambiguation choices or an explanation of absence |

CLI report JSON uses a separate `wire_version` contract (`tracekite schema`).
HTTP routes have their own [OpenAPI contract](../lib/api-spec/openapi.yaml).
Do not assume these are identical payloads. The distribution version, engine
version, wire version, and answer version identify different things.

## Empty results are different answers

| Status | Meaning | Next step |
|---|---|---|
| `present` | Matching results were found | Inspect them and their limits |
| `known_empty` | Known target, no matching results within this graph/query | Check coverage and scope |
| `unknown_target` | The ID/name was not found | Search or list services |
| `ambiguous` | More than one identity matched | Retry with an exact candidate ID |
| `unavailable` | The answer contract represents a failed query | Inspect the error; MCP transport failures may instead be JSON-RPC errors |

In Python 0.2.0, empty `services()` and `deprecations()` collections still carry
`present`; see the [compatibility note](library.md#read-the-whole-envelope).

**Check both `completeness` and `scope.truncation`.** Query budgets are recorded
in truncation and are not always folded into `completeness.complete`.
No combination is permission to delete code: runtime dependencies and unsupported
patterns can remain outside the graph.

## Confidence and provenance

Linker edge payloads can include:

- `confidence`, `min_confidence`, `max_confidence`: rule and fusion scores from
  [configuration](../config/confidence.yml), not measured traffic or a guarantee;
- `detected_by`, `match_type`, `via`: resolver and signals behind the match;
- `source_repo`, `target_repo`, `cross_repo`: available repository attribution
  in MCP/facade edge records (HTTP field names can differ);
- `claim_key`: the matched contract key when one exists;
- `evidence` and `spans`: source citations and their structured file/line form.

Some metadata is empty on aggregate edges. A declaration can describe both
endpoints in one file; do not require two different files to read one assertion.
Confidence says how the edge was established, not how complete the surrounding
graph is. Candidate/rejected edges are excluded from normal MCP traversals.

## Why views show different counts

A Repo view contains source structure; Service Map contains resolved services
and selected service/topic relationships. A package-only repository can have
thousands of source nodes and no resolved services.

The app also distinguishes:

- **stored:** the repository's database totals;
- **loaded:** the bounded dataset returned by the API;
- **displayed:** groups or exact nodes left after projection and filters.

A module group is a visual summary, not another stored source node. Search
can reach nodes outside the loaded sample. [Using the views](using-the-views.md)
explains how to open those nodes and return to the overview.
