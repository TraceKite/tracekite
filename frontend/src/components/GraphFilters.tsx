import { useCallback, useMemo } from "react";
import { LayoutGrid, Boxes, Code, Globe, Package, Zap } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { graphGroupOf } from "@/lib/graphStyle";
import { isLockfileDependencyNode, isNodeVisible } from "@/lib/graphVisibility";
import { VIEW_MODES, type ViewMode } from "@/lib/types";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";
import GraphReadingGuide from "@/components/GraphReadingGuide";
import { NodeTypeFilter, EdgeTypeFilter } from "@/components/GraphTypeFilters";
import { effectiveRepoIds } from "@/lib/graphNavigation";

const VIEW_ICONS: Record<ViewMode, React.ReactNode> = {
  overview: <LayoutGrid className="w-3.5 h-3.5" />,
  architecture: <Boxes className="w-3.5 h-3.5" />,
  code: <Code className="w-3.5 h-3.5" />,
  api: <Globe className="w-3.5 h-3.5" />,
  dependencies: <Package className="w-3.5 h-3.5" />,
  impact: <Zap className="w-3.5 h-3.5" />,
};

export default function GraphFilters() {
  const {
    viewMode, setViewMode, filteredNodeTypes,
    scopeRepoIds, connectionsOnly, setConnectionsOnly, bridgeCount,
    bridgeStatus, hideLockfileDeps, toggleHideLockfileDeps,
    focusNodeId, setFocusNode, nodes, repos, selectedNode, selectedRepo,
    setSelectedNode, setSelectedEdge, setSearchQuery,
  } = useGraphStore();
  const clearExpandedGroup = useGraphNavigationStore(
    (state) => state.clearExpandedGroup);

  // Counted over what the canvas can draw: a group made only of hidden
  // lockfile leaves was reported here ("11 groups") but never drawn ("10").
  const moduleOrder = useMemo(() => {
    const seen = new Set<string>();
    for (const n of nodes as any[]) {
      const key = isNodeVisible(n, filteredNodeTypes, hideLockfileDeps) && graphGroupOf(n);
      if (key) seen.add(key);
    }
    return [...seen].sort();
  }, [nodes, filteredNodeTypes, hideLockfileDeps]);
  const lockfileLeafCount = useMemo(
    () => nodes.filter(isLockfileDependencyNode).length,
    [nodes],
  );
  const scopeCount = effectiveRepoIds(repos, scopeRepoIds, selectedRepo).length;

  const handleViewModeChange = useCallback((mode: ViewMode) => {
    if (mode === "impact") {
      const repoId = selectedNode?.repo_id ?? selectedRepo?.id;
      if (!selectedNode || !repoId) return;
      clearExpandedGroup();
      setSelectedEdge(null);
      setFocusNode(selectedNode.id, repoId);
      setViewMode(mode);
      return;
    }
    clearExpandedGroup();
    setSelectedNode(null);
    setSelectedEdge(null);
    setSearchQuery("");
    setFocusNode(null);
    setViewMode(mode);
  }, [clearExpandedGroup, selectedNode, selectedRepo, setFocusNode,
      setSearchQuery, setSelectedEdge, setSelectedNode, setViewMode]);

  const resetFocusedView = useCallback(() => {
    clearExpandedGroup();
    setSelectedNode(null);
    setSelectedEdge(null);
    setSearchQuery("");
    setFocusNode(null);
    setViewMode("overview");
  }, [clearExpandedGroup, setFocusNode, setSearchQuery, setSelectedEdge,
      setSelectedNode, setViewMode]);

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-2xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <LayoutGrid className="w-3 h-3" /> View Mode
        </h4>
        <div className="grid grid-cols-2 gap-1.5">
          {VIEW_MODES.map((mode) => (
            <button
              key={mode}
              onClick={() => handleViewModeChange(mode)}
              disabled={mode === "impact" && !selectedNode}
              aria-pressed={viewMode === mode}
              title={mode === "impact" && !selectedNode
                ? "Select a node first to inspect its two-hop impact"
                : undefined}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                viewMode === mode
                  ? "bg-slate-900 text-white shadow-xs font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-35"
              }`}
            >
              {VIEW_ICONS[mode]}
              <span className="capitalize">{mode}</span>
            </button>
          ))}
        </div>
      </div>

      <GraphReadingGuide moduleOrder={moduleOrder} viewMode={viewMode} />

      {lockfileLeafCount > 0 && (
        <button
          onClick={toggleHideLockfileDeps}
          aria-pressed={hideLockfileDeps}
          className={`w-full flex items-center justify-between rounded-lg border px-2.5 py-2 text-2xs font-medium transition-colors ${
            hideLockfileDeps
              ? "border-[#315b47]/35 bg-[#315b47]/10 text-[#274a3a]"
              : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
          }`}
        >
          <span>{hideLockfileDeps ? "Lockfile leaves hidden" : "Hide lockfile leaves"}</span>
          <span className="font-mono">{lockfileLeafCount}</span>
        </button>
      )}

      {focusNodeId && (
        <div className="rounded-xl border border-[#9b7a31]/35 bg-[#9b7a31]/10 p-2.5 space-y-2">
          <p className="text-2xs text-[#6f5723] leading-relaxed font-medium">
            {viewMode === "impact"
              ? "Showing the selected node's exact two-hop impact neighborhood."
              : "Showing the focused node's exact local neighborhood."}
          </p>
          <button
            onClick={resetFocusedView}
            className="w-full text-2xs px-2 py-1.5 rounded-md bg-white border border-[#9b7a31]/35
                       text-[#5b461c] hover:bg-[#9b7a31]/10 transition-colors font-medium shadow-xs"
          >
            Return to Overview
          </button>
        </div>
      )}

      {viewMode !== "impact" &&
       (bridgeStatus === "unavailable" || bridgeCount > 0 || scopeCount > 1) && (
        <div className="rounded-xl border border-slate-200 bg-slate-50/80 p-2.5 space-y-2 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">
              Cross-module
            </span>
            <span className="text-2xs font-mono text-slate-500">{bridgeCount}</span>
          </div>
          {bridgeStatus === "unavailable" ? (
            <p className="text-2xs text-amber-800 leading-relaxed font-medium">
              Cross-module connections are unavailable. This is not a verified zero.
            </p>
          ) : bridgeStatus === "loading" ? (
            <p className="text-2xs text-slate-500 leading-relaxed">
              Checking cross-module connections…
            </p>
          ) : bridgeCount === 0 ? (
            <p className="text-2xs text-amber-700 leading-relaxed font-medium">
              No code-level connections between the modules in view.
            </p>
          ) : (
            <>
              <button
                onClick={() => setConnectionsOnly(!connectionsOnly)}
                aria-pressed={connectionsOnly}
                className={`w-full text-2xs px-2 py-1.5 rounded-md transition-all font-medium ${
                  connectionsOnly
                    ? "bg-slate-900 text-white shadow-xs font-semibold"
                    : "bg-white border border-slate-200 text-slate-700 hover:bg-slate-100"}`}
              >
                {connectionsOnly ? "Showing connections only" : "Show connections only"}
              </button>
              <p className="text-2xs text-slate-500 leading-relaxed">
                {bridgeCount} rendered bridge edge{bridgeCount === 1 ? "" : "s"} cross a module boundary.
              </p>
            </>
          )}
        </div>
      )}

      <NodeTypeFilter />
      <EdgeTypeFilter />
    </div>
  );
}
