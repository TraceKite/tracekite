# Contributing

The highest-value contribution is **coverage of a stack we don't handle yet**.
Every ecosystem wires services together differently, and the parsers and
resolvers here reflect the systems the authors happened to have. If your estate
joins services through something we miss, that gap is the contribution.

## Getting set up

```bash
./scripts/setup.sh
docker compose up -d --build
```

Backend tests run outside Docker and need no database:

```bash
uv sync
.venv/bin/python -m pytest backend/tests -q
```

Use `uv`, not a requirements file. Local development, CI, and the container
all resolve the checked-in `uv.lock`; `backend/requirements.txt` was removed
after its older Python and dependency pins caused the environments to diverge.
See the compatibility note at the end of this file.

Frontend typecheck:

```bash
pnpm --filter @tracekite/web run typecheck
```

## The one rule that matters

**Never invent an edge.** This tool's only real asset is that a user can trust
what it draws. An edge that might be right is worse than no edge, because it
costs the user a manual verification they didn't know they needed.

Concretely, that means:

- **Decline and count.** When a signal is ambiguous, don't pick the likeliest
  answer. Return nothing and `ctx.count("r7.ambiguous_host")` so the decline is
  visible in the link run. Reviewers can act on a counter; they cannot act on a
  silent absence.
- **Carry evidence.** Every claim and edge needs `file:line` provenance. If you
  can't cite it, you can't assert it.
- **Never `print` a secret.** Config values are HMAC-redacted at parse time.
  Redaction is applied centrally in `add_claim`, not at each call site, so a new
  emitter cannot forget it — keep it that way.

## Adding a parser

1. Write it in `backend/tracekite/parsers/`. It takes a path and content, and returns
   structured data or `None` — never raises for a file it doesn't recognise.
2. **Detect by shape, not by filename.** One estate's `capability-manifest.json`
   is another's `server.json`. Sniff the content for the structure that makes
   the file what it is, and treat known filenames as a fast path only. See
   `is_mcp_manifest` and `is_asyncapi_file` for the pattern.
3. Register it in `parser_registry.py`.
4. Emit claims from `ingest_claims.py`. A claim is a *statement with a key*
   that something else might independently match.

## Adding a resolver

Resolvers live in `backend/tracekite/services/linker/` as `rN_name.py` and expose
`resolve(index, ctx) -> ResolverOutput`. A resolver joins a `consumes` claim to
a `provides` claim on a shared key and emits an edge with a confidence drawn
from `config/confidence.yml` via `ctx.conf("rN", tier)` — never a hardcoded
float. Register it in `services/linker/registry.py`; nothing else needs editing
to *run* it.

Read `r1_compose.py` first; it is the smallest complete example.

### If your resolver emits a NEW edge type or claim kind

Several registries are **fail-closed**: an unregistered value does not degrade,
it raises, and one unregistered edge type rejects the entire link run. That is
deliberate — a silently-dropped edge type is indistinguishable from a resolver
that found nothing — but it means adding a type is one change across several
files. Do them together:

| Add | Where | What happens if you skip it |
|---|---|---|
| the claim kind | `services/claims.py` → `ACTIVE_KINDS` | `ValueError: Unknown claim kind` at ingest |
| the edge type | `services/graph_writer.py` → `LINKER_EDGE_TYPES` | the whole link run is rejected |
| the resolver | `services/linker/registry.py` | it simply never runs |
| the tier → tier mapping | `services/calibration_tiers.py::edge_tier` | the tier measures as unreachable |
| the confidence tier | `config/confidence.yml` | `ctx.conf` raises |
| a labelled estate | `services/calibration_estates.py` | **`calibrate` fails the build** — invariant 7 forbids serving a tier nobody measured |
| the kinds it reads | `services/linker/incremental.py` → `RESOLVER_KINDS` | incremental relink silently skips your resolver |

`config/confidence.yml` is the single copy and ships inside the wheel as
`tracekite/_control_plane/`; `KG_CONFIG_DIR` overrides its location.

## The API surface, briefly

Most endpoints are per-repository and return that repository's own graph.
Three are estate-wide and worth knowing before you add a view:

| Endpoint | Returns |
|---|---|
| `GET /api/repos/{id}/graph` | one repo's internals — capped, intra-repo edges only |
| `GET /api/v2/service-map` | services and the links between them, whole estate |
| `GET /api/v2/trace` | ranked paths between two services |
| `GET /api/v2/code-bridges?repos=a,b` | where selected repos touch at code altitude |
| `GET /api/config` | operator limits the UI must honour |

`code-bridges` exists because of a trap worth internalising: **a per-repo
graph can never show you a cross-repo relationship.** Its edges are
`CONTAINS`, `DEPENDS_ON`, `DECLARES`, `EXPOSES_API` — all internal. Anything
that crosses a boundary lives on a rendezvous node (`HttpContract`, `Topic`,
`ContractOperation`, `Library`) written by the linker, not by ingestion.

So if you are building a view that should show two repositories relating to
each other, joining their per-repo graphs will silently give you two islands
and no error. Query the rendezvous instead.

`/api/config` serves operator limits — `MAX_SCOPE_REPOS`,
`GRAPH_DETAIL_NODE_LIMIT`, and the service map's edge ceiling — so the UI
enforces the same numbers the deployment sets, without a rebuild. If you add a
limit the frontend must respect, add it there rather than hardcoding it in a
component.

## Traps in the multi-repo code

Each of these cost real time; the comments in the code say the same thing at
the call site.

- **Bridge endpoints must be returned by the bridge query itself.** The
  per-repo sample is capped, and the bridging call site is frequently outside
  it. Assume the endpoints are already on the canvas and the edges dangle.
- **Nodes are tagged with `repo_id` at merge time.** Per-repo responses do not
  carry one, and `NodeDetailsDrawer` needs it to ask the right repository. A
  rendezvous node has no repo at all and must never be looked up by one.
- **"Connections only" filters on participation in a bridge, not node type.**
  A `File` is structure in one place and a call site in another.
- **Zero bridges is a legitimate answer** and is stated in the UI. Two
  repositories that never call each other have nothing between them, and
  saying so is the same decline-don't-guess rule the linker follows.
- **Bridges require a link run.** Ingest alone never produces them.

## Conventions

- Source files stay under ~300 lines. Long files here have always been a sign
  that two ideas got tangled.
- Comments explain **why**, not what. A comment that restates the code is
  noise; one that records the trap you fell into is worth more than the fix.
- Node ids never contain line numbers — line numbers belong in evidence, so
  editing a file above a claim doesn't churn its identity.
- New behaviour needs a test. `backend/tests/` is plain pytest.

## Before you open a PR

```bash
.venv/bin/python -m pytest backend/tests -q
```

If you touched extraction or linking, also re-ingest a repo and run the
accuracy harness — it catches regressions unit tests structurally cannot,
because it compares the graph against real source:

```bash
python scripts/accuracy/verify_edges.py
python scripts/accuracy/measure_recall.py
```

Note that the harness reads the **stored** graph. Re-ingest after changing an
extractor, or you will be measuring the old code's output and chasing a bug
that no longer exists.

## One environment, local and container

They match, so a green test run means something. This is worth stating because
it used not to be true:

| | Python | fastapi | pydantic | neo4j driver |
|---|---|---|---|---|
| container (`backend/Dockerfile` → `uv.lock`) | 3.14 | 0.140.0 | 2.13.4 | 6.2.0 |
| local / CI (`pyproject.toml` → `uv.lock`) | 3.14 | 0.140.0 | 2.13.4 | 6.2.0 |

This used not to be true, and it cost three bugs in one afternoon. The image
was `python:3.12-slim` installing a `backend/requirements.txt` that pinned
pydantic 2.5.3 — a different Python AND a different dependency set from
everything that tested it. Two annotations naming unimported types passed 2063
tests, because Python 3.14 defers annotation evaluation (PEP 649) and never
looked them up, and crashed the container on boot, because 3.12 evaluates them
at import. `requirements.txt` is deleted; the Dockerfile installs `uv.lock`
with `--frozen`, so an image can never quietly resolve something CI did not
test.

Two guards remain, because `requires-python` is `>=3.13` and somebody may run
the floor rather than the ceiling: `check_annotations.py` catches an
annotation-only import statically, and the `container` CI job imports every
module inside the built image.
