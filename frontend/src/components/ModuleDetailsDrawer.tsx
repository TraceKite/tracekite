import { Box, X } from "lucide-react";

import { useGraphStore } from "@/store/graphStore";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";
import { effectiveRepoIds, graphContextKey } from "@/lib/graphNavigation";
import { moduleGroupKey } from "@/lib/graphOverviewProjection";

/**
 * What a module says about itself.
 *
 * A module is an aggregate this UI builds, not a node the graph stores, so
 * there is nothing to fetch for it — everything here was counted when the
 * overview was rolled up.
 */
export default function ModuleDetailsDrawer() {
  const {
    selectedNode, setSelectedNode, repos, selectedRepo, scopeRepoIds, viewMode,
  } = useGraphStore();
  const setExpandedGroup = useGraphNavigationStore((state) => state.setExpandedGroup);
  const groupKey = selectedNode ? moduleGroupKey(selectedNode) : null;
  if (!selectedNode || !groupKey) return null;

  const metadata = selectedNode.metadata ?? {};
  const members = Number(metadata.member_count ?? 0);
  const internalEdges = Number(metadata.internal_edge_count ?? 0);
  const nodeTypes = (metadata.node_types ?? {}) as Record<string, number>;
  const byCount = Object.entries(nodeTypes).sort((a, b) => b[1] - a[1]);
  const openModule = () => setExpandedGroup(
    groupKey,
    graphContextKey(effectiveRepoIds(repos, scopeRepoIds, selectedRepo), viewMode));

  return (
    <aside className="w-80 flex-shrink-0 flex flex-col overflow-hidden bg-[#f4f1e9]
                      border-l border-[#c9c3b7]" aria-label="Module details">
      <div className="flex items-start justify-between gap-2 border-b border-[#dfe2e8] p-4">
        <div className="flex items-center gap-2 min-w-0">
          <Box className="h-4 w-4 shrink-0 text-[#6b6f65]" />
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-[#1a1d23]">{groupKey}</h3>
            <span className="text-2xs text-[#8b929e]">Module</span>
          </div>
        </div>
        <button onClick={() => setSelectedNode(null)} aria-label="Close module details"
          className="shrink-0 text-[#8b929e] transition-colors hover:text-[#1a1d23]">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-xl border border-[#dfe2e8] bg-white/60 p-3">
            <p className="text-xl font-semibold text-[#1a1d23]">{members}</p>
            <p className="text-2xs text-[#8b929e]">Nodes inside</p>
          </div>
          <div className="rounded-xl border border-[#dfe2e8] bg-white/60 p-3">
            <p className="text-xl font-semibold text-[#1a1d23]">{internalEdges}</p>
            <p className="text-2xs text-[#8b929e]">Edges inside</p>
          </div>
        </div>

        <button onClick={openModule}
          className="w-full rounded-md bg-[#315b47]/10 px-2 py-1.5 text-2xs text-[#274a3a]
                     transition-colors hover:bg-[#315b47]/15">
          Open module — double-click it on the canvas
        </button>

        {byCount.length > 0 && (
          <div>
            <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-[#8b929e]">
              What is inside
            </p>
            <div className="space-y-1">
              {byCount.map(([type, count]) => (
                <div key={type}
                  className="flex items-center justify-between rounded-md bg-white/60 px-2 py-1">
                  <span className="truncate text-xs text-[#1a1d23]">{type}</span>
                  <span className="font-mono text-2xs text-[#8b929e]">{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
