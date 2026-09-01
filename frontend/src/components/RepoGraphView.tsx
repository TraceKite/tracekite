import { lazy, Suspense } from "react";
import { useGraphStore } from "@/store/graphStore";
import { useGraphDataLoader } from "@/hooks/useGraphDataLoader";
import GraphFilters from "@/components/GraphFilters";
import GraphControls from "@/components/GraphControls";
import RepoStats from "@/components/RepoStats";
import GraphCanvas2D from "@/components/GraphCanvas2D";
import EmptyState from "@/components/EmptyState";
import { effectiveRepoIds } from "@/lib/graphNavigation";
import GraphDataWarning from "@/components/GraphDataWarning";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import SidebarPanel from "@/components/SidebarPanel";

const GraphCanvas3D = lazy(() => import("@/components/GraphCanvas3D"));

export default function RepoGraphView() {
  const { isFullscreen, repos, selectedRepo, scopeRepoIds, dimension } = useGraphStore();
  useGraphDataLoader();

  const hasRepos = effectiveRepoIds(repos, scopeRepoIds, selectedRepo).length > 0;
  const showEmpty = !hasRepos;
  const showGraphArea = hasRepos;

  return (
    <>
      {!isFullscreen && (
        <SidebarPanel label="Graph controls">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <GraphFilters />
            {dimension === "2d" && <GraphControls />}
            <RepoStats />
          </div>
        </SidebarPanel>
      )}
      <main className="flex-1 relative overflow-hidden"
        style={{
          background: "#fbfaf6",
        }}
      >
        {showEmpty && <EmptyState />}
        {showGraphArea && (dimension === "3d"
          ? <Suspense fallback={<GraphCanvasMessage title="Loading 3D engine…" />}>
              <GraphCanvas3D />
            </Suspense>
          : <GraphCanvas2D />)}
        <GraphDataWarning />
      </main>
    </>
  );
}
