import type { RepoSummary, ViewMode } from "./types.ts";

export interface GraphNavigationContext {
  contextKey: string | null;
  expandedGroup: string | null;
  /**
   * The node whose neighborhood the canvas has been opened into. Separate
   * from the selected node on purpose: selecting reads a node in the drawer,
   * opening replaces what the canvas draws, and one click should not do both.
   */
  expandedNodeId: string | null;
}

export function graphContextKey(repoIds: string[], viewMode: ViewMode): string {
  return `${[...repoIds].sort().join(",")}|${viewMode}`;
}

export function synchronizeGraphContext(
  current: GraphNavigationContext,
  contextKey: string,
): GraphNavigationContext {
  if (current.contextKey === contextKey) return current;
  return { contextKey, expandedGroup: null, expandedNodeId: null };
}

export function activeNavigation(
  current: GraphNavigationContext,
  contextKey: string,
): { expandedGroup: string | null; expandedNodeId: string | null } {
  if (current.contextKey !== contextKey) {
    return { expandedGroup: null, expandedNodeId: null };
  }
  return {
    expandedGroup: current.expandedGroup,
    expandedNodeId: current.expandedNodeId,
  };
}

export interface CameraScene {
  repoIds: string[];
  viewMode: ViewMode;
  focusNodeId: string | null;
  expandedGroup: string | null;
  /** 3D only: the anchor layout the cloud was rebuilt against. */
  layout?: string;
}

/**
 * Identity of the scene a camera frame belongs to.
 *
 * The selected node is deliberately absent. Focusing one narrows the
 * projection but keeps the same nodes at the same coordinates, so re-framing
 * there moved the camera for a reader who never asked it to — which is what
 * made browsing from node to node zoom in and out on its own. A scene changes
 * when the drawn set is rebuilt from scratch: a new scope, view mode, focus
 * fetch, expanded module, or 3D layout.
 */
export function cameraSceneKey({
  repoIds,
  viewMode,
  focusNodeId,
  expandedGroup,
  layout,
}: CameraScene): string {
  return [
    [...repoIds].sort().join(","),
    viewMode,
    layout ?? "",
    focusNodeId ?? "",
    expandedGroup ?? "",
  ].join("|");
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
      ? []
      : draftIds.filter((id) => id !== repoId);
  }
  return draftIds.length >= maxRepos ? draftIds : [...draftIds, repoId];
}
