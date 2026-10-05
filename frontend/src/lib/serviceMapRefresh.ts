import type { LinkerRun } from "./types.ts";

export interface LinkRefreshDecision {
  activeRunId: string | null;
  refresh: boolean;
}

export function observeLinkRun(
  activeRunId: string | null,
  latest: Pick<LinkerRun, "id" | "status"> | null | undefined,
): LinkRefreshDecision {
  if (!latest) return { activeRunId, refresh: false };
  if (latest.status === "running") {
    return { activeRunId: latest.id, refresh: false };
  }
  if (latest.id !== activeRunId) {
    return { activeRunId, refresh: false };
  }
  return { activeRunId: null, refresh: latest.status === "done" };
}
