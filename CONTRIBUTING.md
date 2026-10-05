# Contributing to TraceKite

[Docs](docs/README.md) · [Architecture](docs/design/architecture.md) · [Engineering rules](AGENTS.md)

Useful contributions include missing framework patterns, incorrect or missing
connections with a small reproducer, and unclear documentation. Start from a
specific source example and the edge you expect; **never invent an edge**.

The [architecture](docs/design/architecture.md), [scope](docs/design/GOAL.md), and
[AGENTS.md](AGENTS.md) are normative. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Use [SECURITY.md](SECURITY.md) for vulnerabilities; public reports must not
contain private source or credentials.

## Set up a checkout

You need Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and
Node/pnpm for frontend work. Use the pnpm version in [`package.json`](package.json)
and the Node version used by [frontend CI](.github/workflows/ci.yml).

```bash
git clone https://github.com/TraceKite/tracekite.git
cd tracekite
uv sync --frozen
pnpm install --frozen-lockfile
.venv/bin/python -m pytest backend/tests -q
pnpm --filter @tracekite/web run typecheck
```

Backend unit tests work without a database; live Neo4j tests skip when none is
available. To work on the full app, follow the [app quickstart](docs/quickstart.md).
Use the existing stack and volumes if one is already running.

Do not reintroduce a requirements file or update the lockfile incidentally.
`uv.lock` is shared by local/CI/container installs. The pnpm workspace blocks
npm/yarn installs and enforces a minimum package-release age.

## Where changes belong

| Concern | Location |
|---|---|
| Parse file bytes | `backend/tracekite/parsers/` |
| Extract source facts and claims | `backend/tracekite/services/*_extractor.py`, claim emitters |
| Join claims | `backend/tracekite/services/linker/rN_*.py` |
| Store/query persisted graph | `backend/tracekite/db/` and existing store adapters under `services/` |
| HTTP request handling | `backend/tracekite/routes/` |
| UI rendering / behavior | `frontend/src/components/`, `hooks/`, `lib/`, `store/` |
| Operator policy | `config/*.yml` |

Dependencies point down according to [`layer_map.py`](backend/tools/layer_map.py).
Routes orchestrate; shared graph computation belongs below them. Keep new
production files under 300 lines. When touching an oversized file, extract the
relevant collaborator rather than making it longer. Do not hand-edit vendored
`frontend/src/components/ui/` or generated clients.

## Add a parser or extraction pattern

1. Add a pure bytes/path parser or extend the relevant language extractor.
   Unknown input returns `None`/no facts; unexpected failures name the file.
2. Register new parsers in `parsers/parser_registry.py`. Detect supported
   content shapes, not only one particular filename.
3. Emit through the existing claim sink so identity and redaction stay central.
4. Test positive examples, ambiguous/dynamic declines, and source citations.
5. Add coverage reporting where appropriate; re-ingest real source and run
   the accuracy harness before claiming support.

## Add a resolver

Implement `resolve(index, ctx)` in `services/linker/rN_name.py`; register it in
`services/linker/registry.py`. `r1_compose.py` is a small example.

Read only supplied claims/context. Use `ctx.conf()` from the confidence table;
when a join is ambiguous, emit no edge and increment a named `ctx.count()`.
Normalization must finish before a join resolver sees the key.

A new claim/edge/tier must land with all of its admissions and tests:

| Change | Update |
|---|---|
| Claim kind | `services/claims.py` registry |
| Edge type | Writer allowlist and persistence/reconciliation tests |
| Resolver | Resolver registry and declared phase/order |
| Confidence tier | `config/confidence.yml`, calibration tier mapping and labelled estate |
| Incremental input kinds | `services/linker/incremental.py` |
| New query | Query/classification, envelope/facade parity, bounds, deterministic output |

The writer fails closed: one unregistered edge type rejects the link run.
Calibrated examples and decline tests are required, not just a happy path.

## Traps in the multi-repo code

- A per-repo graph returns intra-repo source relationships. Joining two such
  responses does not create cross-repo bridges; use the contract bridge query.
- Bridge endpoint nodes must be returned even if outside the normal source sample.
- Source nodes need correct `repo_id` attribution for details lookups. Shared
  contract nodes do not belong to a guessed source repo.
- Zero bridges or services can be legitimate. Explain scope/coverage rather than
  drawing invented links. Ingestion queues linking, but those jobs finish separately.
- Repo, Service Map, Trace, and MCP have different traversal semantics;
  see the [graph model](docs/graph-model.md#which-graph-am-i-walking).

The [HTTP guide](docs/api.md) maps routes; OpenAPI is generated from those routes.
The UI uses its own typed client, checked by `test_ui_contract.py`.

## Before opening a PR

```bash
.venv/bin/python -m pytest backend/tests -q
pnpm --filter @tracekite/web run typecheck
pnpm --filter @tracekite/web run test
pnpm --filter @tracekite/web run build
.venv/bin/python backend/tools/check_layers.py
.venv/bin/python backend/tools/check_invariants.py
.venv/bin/python backend/tools/check_annotations.py
.venv/bin/python backend/tools/export_openapi.py --check
```

For extraction/linking changes, rebuild the running code, **re-ingest**, then run
[the accuracy harness](scripts/accuracy/README.md). It checks the stored graph,
so running it against an old ingest does not test your fix. Validate UI changes
in the browser, including empty/error states and shared scope/navigation.

For docs, execute the runnable examples and check links. Keep README as a short
entry point; document every CLI command in [the CLI guide](docs/cli.md), every
MCP tool in [the query reference](docs/mcp-tools.md), and proposals in the
[future index](docs/future/README.md).

Report the concrete change, tests run, and remaining limitations in the PR.
Release publishing has additional [candidate checks](docs/releasing.md).
