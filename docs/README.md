# TraceKite documentation

Start with one path. You do not need to read the design documents to use the app.

## Get a first result

| Your task | Follow this guide |
|---|---|
| Explore a system visually | [App quickstart](quickstart.md) → [Using the views](using-the-views.md) |
| Run a local scan or a CI check | [CLI and artifacts](cli.md) → [Change review](change-review.md) |
| Connect a coding agent | [MCP setup](plugins-and-mcp-guide.md) → [Tool reference](mcp-tools.md) |
| Integrate into a Python application | [Library guide](library.md) |

## Understand the result

- [Use cases](use-cases.md): common developer questions, steps, and expected output.
- [Features and coverage](features.md): what each interface provides.
- [Reading answers](answers.md): source evidence, confidence, status, and completeness.
- [Graph model](graph-model.md): node types, edge types, and direction.
- [Coverage limits](design/coverage-gaps.md): what is missed or intentionally declined.
- [Comparison](comparison.md): how static graph evidence fits with other tools.

## Operate and extend

- [Configuration](configuration.md): ports, credentials, limits, and persistent data.
- [HTTP API](api.md): jobs, graphs, service maps, impact, topics, and review operations.
- [Security and privacy](security-and-privacy.md): where code and outputs go.
- [Contributing](../CONTRIBUTING.md): development setup and required checks.
- [Architecture](design/architecture.md): normative boundaries, pipeline, storage, and invariants.
- [Product scope](design/GOAL.md): what belongs in TraceKite.
- [Accuracy harness](../scripts/accuracy/README.md): measure the stored graph against source.
- [Release process](releasing.md), [dependency updates](dependency-updates.md), and [rename migration](rename-migration.md).

## Plans and historical evidence

The [future and research index](future/README.md) contains proposals, UI design
studies, and dated QA records. These are not instructions for the shipped app.
The [task tracker](../tasks.csv) records work; [CHANGELOG](../CHANGELOG.md) records
released changes.

## Where to check a claim

| Question | Authority |
|---|---|
| What is implemented? | Source and runnable tests; this index links to current guides |
| What should a component guarantee? | [Architecture](design/architecture.md) |
| What does an HTTP endpoint accept? | [Generated OpenAPI](../lib/api-spec/openapi.yaml) and [routes](../backend/tracekite/routes/) |
| What does a CLI command accept? | `tracekite COMMAND --help` |
| What can this scan actually cover? | Scan absence/coverage, query scope, and decline counters |

When contributing docs, keep one task per guide, use a small runnable example,
state its expected result, and link to the reference instead of copying it.
