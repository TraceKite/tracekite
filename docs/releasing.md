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
commit.

## Candidate preparation

1. Update the `tracekite-core` version in
   `packaging/tracekite-core/pyproject.toml`.
2. Move the relevant changelog entries under that version and replace
   `Unreleased` with the release date.
3. Run:

   ```bash
   .venv/bin/python -m pytest backend/tests -q
   pnpm --filter @tracekite/web run typecheck
   pnpm --filter @tracekite/web run test
   pnpm --filter @tracekite/web run build
   ```

4. Build and inspect the distributions:

   ```bash
   rm -rf dist
   uv build --project packaging/tracekite-core --out-dir dist
   uvx --from twine twine check dist/*
   ```

5. Install both the wheel and source distribution into separate clean Python
   3.13 environments and run `scripts/release_smoke.py`.
6. Build the Docker images and verify `/health` through the loopback-only
   deployment.
7. Review `git diff`, package contents, and the release notes for secrets,
   private source, local paths, generated files, and unsupported claims.

## Publish

Create an annotated tag named exactly `v<package-version>` on the reviewed
commit, then publish a GitHub release for that tag.

The `publish-pypi` workflow:

1. rejects a tag/version mismatch;
2. builds the wheel and source distribution from the tag commit;
3. validates and clean-installs both artifacts;
4. records SHA-256 checksums;
5. publishes through PyPI Trusted Publishing;
6. installs the exact version back from PyPI; and
7. attaches the distributions and checksums to the GitHub release.

Do not upload a locally built artifact or move an existing tag to recover a
failed release. Fix the cause, increment the version, and create a new release.
