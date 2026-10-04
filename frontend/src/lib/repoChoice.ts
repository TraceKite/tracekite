/** How a repository is named, and which one a fresh page opens on.
 *
 * A failed ingest still leaves a listed record — deliberately, so a failure is
 * visible rather than vanishing — but one with no owner or repository name. The
 * header then read "/" and the picker showed a blank row, and because the list
 * is newest first, a failure was also the repository a fresh page opened on.
 */

import type { RepoSummary } from "./types.ts";

export function repoFailed(repo: RepoSummary): boolean {
  return repo.ingestion_status === "failed";
}

/** `owner/repo` when both are known, otherwise the stored name or id. */
export function repoLabel(repo: RepoSummary): string {
  if (repo.owner && repo.repo) return `${repo.owner}/${repo.repo}`;
  return repo.name || repo.id;
}

/** The short name a picker row leads with. */
export function repoTitle(repo: RepoSummary): string {
  return repo.repo || repo.name || repo.id;
}

/** The repository to open with: the first that ingested, else the first. */
export function initialRepo(repos: readonly RepoSummary[]): RepoSummary | null {
  return repos.find((repo) => repo.ingestion_status === "completed") ?? repos[0] ?? null;
}
