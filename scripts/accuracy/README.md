# Check graph accuracy against source

[Documentation](../../docs/README.md) · [Contributing](../../CONTRIBUTING.md)

Run these scripts against the Docker application's **stored** graph and cloned
source. Unit/calibration tests use known fixtures; this harness checks real
repositories and can find patterns those fixtures missed.

## Before running

1. Build the backend containing the extraction/linking changes.
2. Re-ingest the relevant repositories and wait for the automatic link run.
3. Install the development environment with `uv sync --frozen`.
4. Keep the source clone used by ingestion available in the backend container.

From the repository root:

```bash
.venv/bin/python scripts/accuracy/verify_edges.py
.venv/bin/python scripts/accuracy/measure_recall.py
```

Both default to every stored repository. Pass specific repo IDs to narrow the
run; use IDs from `/api/repos`:

```bash
.venv/bin/python scripts/accuracy/verify_edges.py spring-petclinic_spring-petclinic-cloud
.venv/bin/python scripts/accuracy/measure_recall.py spring-petclinic_spring-petclinic-cloud
```

Do not use `--help` to discover options: these scripts execute their checks.
`verify_edges.py` accepts `--json` for a detailed machine-readable report.

## Interpret the output

| Check | Direction | Scope |
|---|---|---|
| Precision (`verify_edges.py`) | Edge → cited source | Samples HTTP/MCP exposures, service calls, HTTP invocations, SQL reads/writes |
| Recall (`measure_recall.py`) | Source fact → stored graph | Enumerates admitted Compose dependencies, supported Next.js handlers, gateway routes, MCP manifests |

Precision verdicts: `TP` supported, `TP_WEAK` supported without a literal match
for every detail, `FP?` needs manual inspection, `UNVERIFIABLE` could not be
checked mechanically. Read every suspected false positive and unverifiable case
before reporting a score; either the graph or checker may be wrong.

Recall enumerates files admitted by the stored scan. Production Compose checks
exclude test files. Shared facts attributed to another repo are reported as
present, not missing. A category with no source examples is 0/0, not evidence of
perfect coverage.

Neither script is a universal pass/fail release gate by exit code alone; inspect
the reported findings. Messaging, package, gRPC, and GraphQL recall do not have
complete source enumerators here.

## Connection settings

[`_kg.py`](_kg.py) uses:

| Variable | Default |
|---|---|
| `TRACEKITE_NEO4J_CONTAINER` | `tracekite-neo4j` |
| `TRACEKITE_BACKEND_CONTAINER` | `tracekite-backend` |
| `NEO4J_USER` | `neo4j` |
| `NEO4J_PASSWORD` | Environment value, otherwise repository `.env` |
| `TRACEKITE_REPO_ROOT` | `/app/data/repos` inside the backend container |
| `TRACEKITE_REPO` | Optional comma-separated repo IDs instead of arguments |

The harness reads files from the ingested clone, not your host working tree.
Submodules missing from that clone cannot be used as expected ground truth.
After changing extraction code, a score from an older stored ingest does not
validate the change.
