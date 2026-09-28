# Reviewing dependency updates

Dependabot opens weekly pull requests for pip, npm, GitHub Actions and both
Dockerfiles (`.github/dependabot.yml`). A green CI run is necessary but not
sufficient to merge one, because CI does not exercise everything these pull
requests change. This is the procedure that closes the gaps.

## What CI does and does not cover

| Change | Covered by CI? | Check it yourself |
|---|---|---|
| npm packages and `pnpm-lock.yaml` | `frontend` job: frozen install, typecheck, test, build | whether the package is used at all; release age |
| `backend/Dockerfile` | `container` job builds and smoke-tests the image | — |
| `frontend/Dockerfile` (node, nginx) | **no** — nothing builds this image | build and run it |
| Actions used by `ci.yml` | yes, on the pull request | breaking changes in release notes |
| Actions used only by `publish-pypi.yml` / `publish-artifact.yml` | **no** — those run on release / push to `main` | inputs they pass still exist |
| pip pins in `pyproject.toml` | **partly** — `uv sync --frozen` installs from `uv.lock` and does not check it against the pins | `uv lock --check` |

## Procedure

1. **List and read every open pull request.**

   ```bash
   gh pr list --state open --json number,title,headRefName,mergeStateStatus
   gh pr diff <n>
   gh pr checks <n>
   ```

2. **Check the release age.** `pnpm-workspace.yaml` requires every npm release
   to be at least a day old (`minimumReleaseAge: 1440`). Check the new version
   and any transitive packages the lockfile diff introduces:

   ```bash
   npm view <package> time --json | jq -r '."<version>"'
   ```

3. **Check whether the code uses it.** A major bump of a package nothing
   imports cannot break the app — but is a hint the dependency should go.

   ```bash
   grep -rlE "from .<package>." frontend/src lib
   ```

   In zsh, write the pattern with `${package}` braces; `$package[...]` is
   parsed as an array subscript.

4. **Read release notes for major versions.** For GitHub Actions, list the
   inputs every workflow passes (`grep -A6 "uses: <action>" .github/workflows/*.yml`)
   and confirm none was removed or changed meaning — including in the publish
   workflows, which never run on a pull request.

5. **Merge them all locally first**, in the order they will be merged, so the
   combination is tested rather than each one alone:

   ```bash
   for n in <numbers>; do git fetch -q origin pull/$n/head:pr-$n; done
   git checkout -b tmp/deps-check origin/main
   for n in <numbers>; do git merge -q --no-edit pr-$n || echo "conflict in #$n"; done
   ```

6. **Prove the merged lockfile is what pnpm would produce.** Pull requests
   that merge without textual conflict can still combine into a lockfile pnpm
   would not have written; re-resolving also re-applies the release-age rule.

   ```bash
   pnpm install --frozen-lockfile
   pnpm install --lockfile-only && git diff --stat pnpm-lock.yaml   # expect no diff
   pnpm --filter @tracekite/web run typecheck
   pnpm --filter @tracekite/web run test
   pnpm --filter @tracekite/web run build
   pnpm -r --if-present run typecheck
   ```

   Run anything else a bumped tool drives — for `tsx`,
   `pnpm --filter ./scripts run hello`.

7. **Build and run the frontend image** when node or nginx moved — see step 7
   of [the release checklist](releasing.md#candidate-preparation).

8. **Open the app** with the merged dependencies and confirm it renders with no
   console errors. React throws at startup, not at build, when `react` and
   `react-dom` disagree; `reactRuntimePairing.test.ts` guards the pair.

9. **Merge in the tested order**, squashed like the rest of the history, and
   confirm the result is the tree that was tested:

   ```bash
   gh pr merge <n> --squash
   git fetch origin && git diff --stat tmp/deps-check origin/main   # expect nothing
   ```

   Then delete the local `tmp/deps-check` and `pr-*` refs.

## Correcting a pull request instead of merging it

If a pull request is wrong — a broken build, a removed input still in use, a
release younger than a day — fix it in its own branch or a follow-up pull
request rather than merging it red. Pushing to a Dependabot branch stops
Dependabot updating that pull request, which is acceptable only if it is
merged immediately afterwards.

## Known gaps

- Dependabot's pip updates change the pins in the root `pyproject.toml` but not
  `uv.lock` or `packaging/tracekite-core/pyproject.toml`, so the pins can claim
  versions that nothing is tested with. `uv lock --check` shows the drift.
- `frontend/Dockerfile` is built by no workflow; until CI builds it, step 7 is
  the only check.
