# Claude Code — working in this repo

The engineering guidelines live in one place and are imported here rather than
copied, so the two files cannot drift apart:

@AGENTS.md

Everything below is operational context specific to running as an agent here.
It does not restate the rules.

## Read before changing anything

`docs/design/architecture.md` is normative for layering and the data model, and
is worth reading in full before touching `backend/evigraph/services/linker/` or
`backend/evigraph/db/`. `CONTRIBUTING.md` §"Traps in the multi-repo code" documents
failure modes that each cost real debugging time — the per-repo graph silently
returning two islands instead of an error is the one that catches everyone.

`.agents/memory/` is an agent's own notes between sessions. It is untracked,
so it exists only if this working copy has one; when it does, its index is
worth reading before diagnosing anything involving Neo4j edge properties, the
writer allowlist, or health checks through the preview proxy.

## Environment

The venv is **not** checked out. Create it from the lockfile, once per clone:

```bash
uv sync
```

`uv.lock` resolves the versions in `pyproject.toml` and puts the environment
at the repo root, not under `backend/`. The container installs the same lock
with `--frozen`, so the image runs the versions the tests ran against — it did
not always, and the gap cost three bugs (see CONTRIBUTING.md). The old
`backend/requirements.txt`, which pinned a pydantic with no wheel for 3.13+,
is deleted; do not reintroduce it.

Node is a pnpm workspace; `npm` and `yarn` are blocked by a preinstall guard.
`pnpm-workspace.yaml` enforces a 1-day minimum release age on every npm package
as supply-chain defence — do not disable it to unblock an install.

## Verifying a change

Prefer the narrow check while iterating and the full one before reporting done:

```bash
.venv/bin/python -m pytest backend/tests -q
```

```bash
pnpm --filter @evigraph/web run typecheck
```

The accuracy harness under `scripts/accuracy/` reads the **stored** graph, not
your working tree. Re-ingest after changing an extractor or you will be
measuring the previous code and chasing a bug that no longer exists.

## Reporting

State what you ran and what it returned. If a test fails, show the output
rather than describing it. If part of the work is incomplete, say which part —
a partial change reported as finished is more expensive here than an obvious
failure, because the graph will still render, just wrongly.
