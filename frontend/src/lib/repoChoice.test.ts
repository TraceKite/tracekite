import assert from "node:assert/strict";
import test from "node:test";

import { initialRepo, repoFailed, repoLabel, repoTitle } from "./repoChoice.ts";
import type { RepoSummary } from "./types.ts";

const repo = (overrides: Partial<RepoSummary>): RepoSummary => ({
  id: "acme_shop", name: "acme/shop", owner: "acme", repo: "shop",
  github_url: "https://github.com/acme/shop", branch: "main",
  ingestion_status: "completed", node_count: 10, edge_count: 5,
  ...overrides,
} as RepoSummary);

/** What a failed ingest leaves behind: an id, a status, and nothing else. */
const failed = repo({ id: "strapi_strapi", name: "strapi_strapi", owner: "", repo: "",
                      ingestion_status: "failed", node_count: 0 });

test("a repository with an owner and name reads owner/repo", () => {
  assert.equal(repoLabel(repo({})), "acme/shop");
});

test("a failed ingest is labelled by its stored name, never by a bare slash", () => {
  assert.equal(repoLabel(failed), "strapi_strapi");
  assert.equal(repoTitle(failed), "strapi_strapi");
  assert.ok(repoFailed(failed));
});

test("a fresh page opens on a repository that ingested, not on a failure", () => {
  // The list is newest first, so a just-failed ingest sits at the top.
  assert.equal(initialRepo([failed, repo({})])?.id, "acme_shop");
});

test("with nothing ingested, the first repository is still chosen", () => {
  assert.equal(initialRepo([failed])?.id, "strapi_strapi");
  assert.equal(initialRepo([]), null);
});
