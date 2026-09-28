# Release process

This checklist prepares and publishes `tracekite-core`. The Docker application
is distributed as source and is not pushed to a container registry by this
workflow.

## One-time repository setup

1. Make the repository publicly readable.
2. Enable GitHub private vulnerability reporting.
3. Create a protected GitHub environment named `pypi` with required
   maintainer approval.
4. Configure a PyPI Trusted Publisher for:
   - owner: `TraceKite`;
   - repository: `tracekite`;
   - workflow: `publish-pypi.yml`; and
   - environment: `pypi`.
5. Protect the default branch and require the test, container, frontend,
   and wheel-smoke CI jobs.

These are external account settings and cannot be established by a repository
commit. Check them before every first release on a new account:

```bash
gh repo view TraceKite/tracekite --json visibility
gh api repos/TraceKite/tracekite/environments --jq '.environments[] | {name, rules: [.protection_rules[].type]}'
gh api repos/TraceKite/tracekite/private-vulnerability-reporting --jq .enabled
gh api repos/TraceKite/tracekite/rulesets --jq '.[] | {name, enforcement}'
```

The Trusted Publisher lives on PyPI and cannot be read from GitHub: check it
signed in at <https://pypi.org/manage/account/publishing/>. Before the first
upload it is a *pending* publisher, and a pending publisher **does not reserve
the project name** — anyone can register it until the first upload succeeds.

## Candidate preparation

1. Update the version everywhere it must match. `test_agent_setup` fails if
   these disagree:
   - `packaging/tracekite-core/pyproject.toml` (the published package — the
     release workflow checks the tag against this one);
   - `pyproject.toml`;
   - `plugins/tracekite/kimi.plugin.json`,
     `plugins/tracekite/.claude-plugin/plugin.json` and
     `plugins/tracekite/.codex-plugin/plugin.json`; and
   - the `name = "tracekite"` entry in `uv.lock`. Edit that one line rather
     than running `uv lock`, which also upgrades anything whose pin has
     drifted from the lock — a dependency change that does not belong in a
     version bump.
2. Move the relevant changelog entries under that version and replace
   `Unreleased` with the release date.
3. Run:

   ```bash
   .venv/bin/python -m pytest backend/tests -q
   pnpm --filter @tracekite/web run typecheck
   pnpm --filter @tracekite/web run test
   pnpm --filter @tracekite/web run build
   ```

4. **Run the backend suite the way the release job will.** The release build
   uses `actions/setup-python` with Python 3.13 on Linux — the oldest Python the
   package supports, and one that starts worker processes with `fork()`. A local
   macOS or Python 3.14 run does neither and cannot catch fork-only defects;
   0.1.0 failed exactly there. From a clean clone, so git behaves:

   ```bash
   git clone -q --branch <candidate-branch> . /tmp/tk-release-check
   docker run --rm -v /tmp/tk-release-check:/src:ro \
     ghcr.io/astral-sh/uv:python3.13-bookworm-slim sh -c '
       apt-get update -qq && apt-get install -y -qq git >/dev/null
       cp -r /src /work && cd /work
       git config --global --add safe.directory "*"
       UV_PYTHON_PREFERENCE=only-system uv sync --frozen -q --python 3.13
       .venv/bin/python -m pytest backend/tests -q
       .venv/bin/python backend/tools/check_layers.py
       .venv/bin/python backend/tools/check_invariants.py
       .venv/bin/python backend/tools/export_openapi.py --check'
   ```

   The image needs `git` installed, or the git-dependent tests fail for reasons
   that have nothing to do with the candidate.

5. Build and inspect the distributions:

   ```bash
   rm -rf dist
   uv build --project packaging/tracekite-core --out-dir dist
   uvx --from twine twine check dist/*
   ```

6. Install both the wheel and source distribution into separate clean Python
   3.13 environments and run `scripts/release_smoke.py`:

   ```bash
   for kind in whl tar.gz; do
     uv venv -q --python 3.13 /tmp/tk-smoke-${kind%%.*}
     uv pip install -q --python /tmp/tk-smoke-${kind%%.*}/bin/python dist/*.$kind
     /tmp/tk-smoke-${kind%%.*}/bin/python scripts/release_smoke.py \
       --tracekite /tmp/tk-smoke-${kind%%.*}/bin/tracekite --repo-root .
   done
   ```

7. Build the Docker images and verify `/health` through the loopback-only
   deployment. CI builds only the backend image; **nothing in CI builds
   `frontend/Dockerfile`**, so build and run it by hand. nginx refuses to start
   if the `backend` upstream cannot be resolved, so give it one:

   ```bash
   docker build -f frontend/Dockerfile -t tracekite-frontend:candidate .
   docker run -d --rm --name tk-web --add-host backend:127.0.0.1 \
     -p 127.0.0.1:28099:80 tracekite-frontend:candidate
   docker exec tk-web nginx -t
   curl -sI http://127.0.0.1:28099/ | head -1
   docker stop tk-web
   ```

8. Review `git diff`, package contents, and the release notes for secrets,
   private source, local paths, generated files, and unsupported claims. A quick
   pass over the built distributions:

   ```bash
   { unzip -Z1 dist/*.whl; tar tzf dist/*.tar.gz; } \
     | grep -iE '(^|/)\.env|secret|\.pem$|\.key$|__pycache__|/tests?/'
   ```

## Publish

Create an annotated tag named exactly `v<package-version>` on the reviewed
commit, then publish a GitHub release for that tag.

1. Draft the release against the exact commit that was reviewed, so later
   pushes to `main` cannot change what gets tagged. A draft is visible only to
   maintainers, creates no tag and does not start the workflow:

   ```bash
   gh release create v<version> --draft --target <full-commit-sha> \
     --title "TraceKite <version>" --notes-file <notes.md>
   ```

2. Tag that commit and push the tag. A tag push starts no workflow here:

   ```bash
   git tag -a v<version> <full-commit-sha> -m "tracekite-core <version>"
   git push origin v<version>
   ```

3. Publish the draft (**Publish release** in the UI, or
   `gh release edit v<version> --draft=false`). Publishing makes the release
   public and starts `publish-pypi`.

4. **Approve the upload only after the `build` job has succeeded.** The
   workflow pauses at the protected `pypi` environment; check the run first:

   ```bash
   gh run list --workflow publish-pypi.yml --limit 1
   gh run view <run-id> --json jobs --jq '.jobs[] | "\(.name): \(.conclusion)"'
   ```

   Approve in the run's page, or with
   `gh api repos/TraceKite/tracekite/actions/runs/<run-id>/pending_deployments`
   (`environment_ids`, `state=approved`). This is the step that cannot be
   undone: a version uploaded to PyPI can never be uploaded again.

The `publish-pypi` workflow:

1. rejects a tag/version mismatch;
2. builds the wheel and source distribution from the tag commit;
3. validates and clean-installs both artifacts;
4. records SHA-256 checksums;
5. publishes through PyPI Trusted Publishing;
6. installs the exact version back from PyPI; and
7. attaches the distributions and checksums to the GitHub release.

## When a release build fails

Do not upload a locally built artifact or move an existing tag to recover a
failed release. Fix the cause, increment the version, and create a new release.

1. Read the failure: `gh run view <run-id> --log-failed`. If the `build` job
   failed, nothing was uploaded and nothing waits for approval.
2. Reproduce it where it failed — usually the Linux Python 3.13 run in
   candidate step 4 — and confirm the unfixed tree fails the same way before
   trusting a fix. Do not re-run the release to see whether it passes: a
   failure specific to the release environment fails again, and one that
   passes on retry is a defect the release would ship.
3. Fix it in a pull request, bump to the next patch version (candidate step 1)
   and say in `CHANGELOG.md` that the failed version was tagged but never
   published.
4. Leave the failed tag and its release where they are, and add one line to
   the release notes saying it was not published and which version replaces it.
5. Release the new version from the top of this document.

## Known traps

- **`fork()` and threads.** Workers that start with `fork()` (Linux before
  Python 3.14) inherit a thread pool's bookkeeping but none of its threads.
  Module-level executors must be replaced in the child — see
  `services/parse_budget.py` and its `os.register_at_fork` hook — or the worker
  waits on threads that do not exist.
- **The release interpreter is not CI's.** CI's `test` job lets uv provide
  Python; the release job uses `actions/setup-python`. They ran the same test
  suite with different results on 0.1.0.
- **`uv sync --frozen` does not check the lock against `pyproject.toml`.** A pin
  can drift from what is actually installed and tested without any job
  failing; `uv lock --check` shows it.
- **The frontend image is not built in CI.** Base-image bumps to
  `frontend/Dockerfile` are verified only by building it (candidate step 7).
