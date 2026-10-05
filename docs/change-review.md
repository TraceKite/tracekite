# Review changes with artifacts

[Docs](README.md) · Prerequisite: [CLI and artifacts](cli.md)

Compare the same repository set before and after a change. TraceKite reports
indexed connections that disappeared, with available consumer citations.
It does not execute tests or prove a runtime failure.

## Build a no-change baseline

From the TraceKite checkout used in the CLI demo:

```bash
base_orders=$(tracekite artifact corpus/orders-service --repo-id orders-service \
  --head-sha "$(git rev-parse HEAD)" --out ./tk-base)
base_billing=$(tracekite artifact corpus/billing-service --repo-id billing-service \
  --head-sha "$(git rev-parse HEAD)" --out ./tk-base)

tracekite pr --base "$base_orders" "$base_billing" \
  --head "$base_orders" "$base_billing" --changed-repo billing-service
```

Expected: empty losses and exit `0`. Using the identical snapshot here verifies
the command before introducing a real change.

## Compare a real branch

1. Check out the base revisions in separate directories or Git worktrees.
2. Build one artifact per repository, with stable `--repo-id` values and each
   repository's actual `--head-sha`.
3. Repeat for the head revisions using the same engine, configuration, and
   redaction key. Reuse unchanged repositories' artifacts.
4. Supply the **complete base and head sets**, including consumers that did not
   change. Omitting a consumer prevents it from appearing in the report.

Replace the filenames below with the paths printed by `artifact`:

```bash
tracekite pr \
  --base ./base/orders.tracekite ./base/billing.tracekite \
  --head ./head/orders.tracekite ./head/billing.tracekite \
  --changed-repo billing-service --comment > impact.md
```

`--base` and `--head` take artifact files, not branch names. `--comment` renders
Markdown locally; it does not post a comment to GitHub.

Repeat `--changed-repo` for every changed repository. In a monorepo, also supply
every changed path with `--changed-file 'repo-id:relative/path'`. This lets the
policy distinguish a changed provider from an unchanged consumer in the same
repository. TraceKite trusts these flags; it does not validate them against Git.

Read `breaks`, `unexplained`, and `risk` in JSON output. Exit `1` means the
current policy attributes a blocking loss to the change. Exit `0` can still
mean missing inputs or unsupported extraction; read the evidence and coverage.

## Other checks

The variables below are artifact paths from your base/head builds:

| Task | Command | Interpretation |
|---|---|---|
| Compare one repository's structure | `tracekite diff "$base_orders" "$head_orders"` | Exit `1` if nodes or edges changed |
| Compare declarations and code in one snapshot | `tracekite drift "$head_orders" "$head_billing"` | HTTP, gRPC, and topic mismatches; “observed” means found in source |
| Find contract changes still used by consumers | `tracekite drift "$head_orders" "$head_billing" --base "$base_orders" "$base_billing"` | Temporal drift between supplied sets |
| Inspect deprecations | `tracekite deprecations "$head_orders" "$head_billing"` | Deprecated contracts and active indexed consumers |
| Recheck citations against a checkout | `tracekite reverify "$head_orders" --repo-root /path/to/orders` | Read-only report; does not modify artifacts or the app |
| Inspect one repo through time | `tracekite history "$base_orders" "$head_orders"` | Supply snapshots oldest first; each file is one time point |

Reverify one repository at a time when evidence paths are relative to different
checkout roots. An empty consumer list is a finding within the supplied inputs,
not permission to delete a contract.

## CI integration

Install `tracekite-core`, download the exact artifact sets, and run the command
above in your CI job. Retain the report and the input commit IDs. Your CI system
decides whether to block, notify, or request review.

The [release smoke test](../scripts/release_smoke.py) exercises a complete PR
comparison. The [artifact workflow](../.github/workflows/publish-artifact.yml)
shows snapshot publication for this repository; its `uv sync` and source paths
assume the TraceKite layout, so adapt it rather than calling it unchanged from
an unrelated project. No organization discovery or GitHub comment posting is
installed by `pip install`.
