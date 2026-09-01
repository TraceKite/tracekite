import type { RepoSummary, ViewMode } from "./types.ts";

export interface GraphNavigationContext {
  contextKey: string | null;
  expandedGroup: string | null;
}

export function graphContextKey(repoIds: string[], viewMode: ViewMode): string {
  return `${[...repoIds].sort().join(",")}|${viewMode}`;
}

export function synchronizeGraphContext(
  current: GraphNavigationContext,
  contextKey: string,
): GraphNavigationContext {
  if (current.contextKey === contextKey) return current;
  return { contextKey, expandedGroup: null };
}

export function activeExpandedGroup(
  current: GraphNavigationContext,
  contextKey: string,
): string | null {
  return current.contextKey === contextKey ? current.expandedGroup : null;
}

export function effectiveRepoIds(
  repos: RepoSummary[],
  scopeRepoIds: string[],
  selectedRepo: RepoSummary | null,
): string[] {
  if (scopeRepoIds.length > 0) return scopeRepoIds;
  if (repos.length > 0) return repos.map((repo) => repo.id);
  return selectedRepo ? [selectedRepo.id] : [];
}

export function toggleDraftRepoScope(
  draftIds: string[],
  repoId: string,
  maxRepos: number,
): string[] {
  if (draftIds.length === 0) return [repoId];
  if (draftIds.includes(repoId)) {
    return draftIds.length === 1
      ? draftIds
      : draftIds.filter((id) => id !== repoId);
  }
  return draftIds.length >= maxRepos ? draftIds : [...draftIds, repoId];
}
