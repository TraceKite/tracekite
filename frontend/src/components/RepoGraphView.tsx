import { useGraphStore } from "@/store/graphStore";
import GraphFilters from "@/components/GraphFilters";
import GraphControls from "@/components/GraphControls";
import RepoStats from "@/components/RepoStats";
import GraphCanvas2D from "@/components/GraphCanvas2D";
import EmptyState from "@/components/EmptyState";

export default function RepoGraphView() {
  const { isFullscreen, selectedRepo, scopeRepoIds } = useGraphStore();
  // The Repo tab now obeys the shared scope, so a selection made on
  // Service Map or Trace opens this view too.
  const hasRepos = scopeRepoIds.length > 0 || !!selectedRepo;
  const showEmpty = !hasRepos;
  const showGraphArea = hasRepos;

  return (
    <>
      {!isFullscreen && (
        <aside className="w-72 flex-shrink-0 border-r border-[#2b313a] bg-[#15181c]/50 flex flex-col overflow-hidden z-10 shadow-xl">
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            <GraphFilters />
            <GraphControls />
            {selectedRepo && <RepoStats />}
          </div>
        </aside>
      )}
      <main className="flex-1 relative overflow-hidden"
        style={{
          background: "radial-gradient(ellipse at 20% 50%, rgba(59,130,246,0.08) 0%, transparent 50%), radial-gradient(ellipse at 80% 20%, rgba(139,92,246,0.08) 0%, transparent 50%), radial-gradient(ellipse at 50% 80%, rgba(236,72,153,0.05) 0%, transparent 50%), linear-gradient(180deg, #0e1013 0%, #15181c 100%)",
        }}
      >
        {showEmpty && <EmptyState />}
        {showGraphArea && <GraphCanvas2D />}
        {/* IngestionStatus moved to App: it must survive a tab switch, and the
            guard here excluded `completed` and `failed` — the only two states
            the panel was built to report. */}
      </main>
    </>
  );
}