# Release record: 0.1.0 and 0.1.1, 2026-09-28

A dated record of the first `tracekite-core` release, not the live process.
[`docs/releasing.md`](../releasing.md) and
[`docs/dependency-updates.md`](../dependency-updates.md) are current and were
rewritten from what is recorded here.

## Before the release

- **#29, service-map fixes** — reviewed, fifteen findings fixed and verified in
  the browser against the live estate, squash-merged as `96e1c53`.
- **#21–#28, Dependabot** — reviewed and squash-merged in order: node 26 and
  nginx 1.31 for the frontend image, setup-uv v7, `@radix-ui/react-toast`,
  `@radix-ui/react-switch`, `sonner`, `tsx` and `framer-motion` 13. All eight
  passed CI, but CI does not build the frontend image or run the publish
  workflows, so they were also merged together locally first and checked: no
  conflicts; the combined lockfile reproduced byte for byte by
  `pnpm install --lockfile-only`; every new npm version older than the one-day
  minimum; the frontend image built and served by nginx 1.31.6. `framer-motion`, the only major npm bump, is
  imported nowhere. `origin/main` after the merges was byte-identical to the
  tree that was tested.

## 0.1.0 — tagged, never published

The candidate was `f801d56`: the changelog entry had been dated at `7379fc0`,
where `docker compose build frontend` fails because node 25 dropped corepack.
Local checks passed — backend and frontend suites, `twine check`, clean wheel
and sdist installs with `release_smoke.py`, a scan of the package contents —
and so did the one-time setup: repository public, `pypi` environment with
required reviewers, private vulnerability reporting, a ruleset on `main`, and a
pending Trusted Publisher on PyPI.

The release was drafted against `f801d56`, tagged `v0.1.0` (annotated) and
published. Its `publish-pypi` run
([36382091861](https://github.com/TraceKite/tracekite/actions/runs/36382091861))
failed at *Test the release source*: two byte-equivalence tests failed, seven
files logged `Parse timed out after 30s`, and the suite took 323s instead of
about 28. `publish`, `verify-registry` and `release-assets` were skipped;
nothing reached PyPI and there was no approval to give.

## The defect

Every parse runs on a module-level `ThreadPoolExecutor` so a pathological file
can be abandoned after its budget. Sharded and parallel scans start workers
with `fork()` where that is the default — Linux before Python 3.14 — and a
forked child inherits the executor's bookkeeping but none of its threads. Once
the parent had parsed anything, each parse in a child queued behind threads
that did not exist, timed out and was dropped, and the parallel artifact
differed from the serial one.

Reproduced on Linux with Python 3.13: a child's parse returned at once while
the parent had not used the pool, and timed out once it had. It stayed hidden
because macOS and Python 3.14 do not fork by default, and because the regular
CI run had no threads alive when those tests forked (no fork-with-threads
warning, against 28 in the release run). The release job gets Python from
`actions/setup-python`; CI's `test` job lets uv provide it.

Re-running the release was not an option: the failure was specific to the
release environment, and `docs/releasing.md` says a failed release is fixed and
re-versioned, never retried under its tag.

## 0.1.1 — the fix

[#30](https://github.com/TraceKite/tracekite/pull/30), squash-merged as
`53ac501`:

- `services/parse_budget.py` owns the pool and replaces it in each forked child
  with `os.register_at_fork`. Workers keep `fork()`: the engine config is a
  module global they inherit, and `spawn` would silently run them on defaults.
  The module is extracted from `scan.py`, which drops from 324 to 299 lines.
- `test_parse_budget.py` forces fork on every platform and fails on the
  previous code; it also covers the budget abandoning an overrunning parse.
- The version became 0.1.1 in all five places `test_agent_setup` keeps equal,
  plus the root line of `uv.lock` — a full `uv lock` would also have upgraded
  two tree-sitter grammars whose root pins had drifted from the lock.

Full suite, Linux with system Python 3.13, clean clones with git installed:

| Tree | Result | Time |
|---|---|---|
| `main` at `f801d56` | 2 failed — the release failures — 2411 passed, 38 skipped | 303s |
| fix branch | 2415 passed, 38 skipped | 49s |

The release was tagged `v0.1.1` on `53ac501` and published. Its `publish-pypi`
run ([36384861723](https://github.com/TraceKite/tracekite/actions/runs/36384861723))
passed the build job — 2415 backend tests in 56s with no parse timeouts, the
web app, `twine check` and both smoke installs — and the upload was approved
at the `pypi` gate after that.

The `publish` job uploaded both files through the Trusted Publisher at 06:52
UTC, creating the `tracekite-core` project on PyPI and turning the pending
publisher into an ordinary one. `verify-registry` installed 0.1.1 back from
PyPI and `release-assets` attached the wheel, the sdist and `SHA256SUMS` to the
release. The PyPI digests match `SHA256SUMS` — wheel `c9cb0c9b…`, sdist
`918f627a…` — and a fresh `uv pip install tracekite-core==0.1.1` from PyPI
runs `tracekite --help`.

The v0.1.0 release notes now say it was not published and point to v0.1.1; its
tag stays on `f801d56`.

## Follow-ups left open

- Build `frontend/Dockerfile` in CI; today only a hand-run build checks it.
- Reconcile the root `pyproject.toml` pins with `uv.lock` — Dependabot's pip
  updates change the pins only — and consider `uv lock --check` in CI.
- Run the backend suite in CI under the same interpreter the release job uses.
- Remove `framer-motion`, which nothing imports.
