import { useState, useCallback, useMemo } from "react";
import {
  LayoutGrid, Boxes, Code, Globe, Package, Zap,
  Filter, ChevronDown, ChevronRight, Eye, EyeOff,
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { graphGroupOf, EDGE_COLORS } from "@/lib/graphStyle";
import { isLockfileDependencyNode } from "@/lib/graphVisibility";
import { NODE_TYPES, EDGE_TYPES, VIEW_MODES, type ViewMode } from "@/lib/types";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";
import GraphReadingGuide from "@/components/GraphReadingGuide";
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
    viewMode, setViewMode,
    filteredNodeTypes, setFilteredNodeTypes,
    filteredEdgeTypes, setFilteredEdgeTypes,
    scopeRepoIds, connectionsOnly, setConnectionsOnly, bridgeCount,
    bridgeStatus, hideLockfileDeps, toggleHideLockfileDeps,
    focusNodeId, setFocusNode, nodes, links, repos, selectedNode, selectedRepo,
    setSelectedNode, setSelectedEdge, setSearchQuery,
    highlightedEdgeTypes, toggleHighlightEdgeType, clearHighlightedEdgeTypes,
  } = useGraphStore();
  const clearExpandedGroup = useGraphNavigationStore(
    (state) => state.clearExpandedGroup);

  const moduleOrder = useMemo(() => {
    const seen = new Set<string>();
    for (const n of nodes as any[]) {
      const key = graphGroupOf(n);
      if (key) seen.add(key);
    }
    return [...seen].sort();
  }, [nodes]);
  const nodeTypes = useMemo(
    () => [...new Set([...NODE_TYPES, ...nodes.map((node) => node.type)])],
    [nodes],
  );
  const edgeTypes = useMemo(
    () => [...new Set([...EDGE_TYPES, ...links.map((link) => link.type)])],
    [links],
  );
  const lockfileLeafCount = useMemo(
    () => nodes.filter(isLockfileDependencyNode).length,
    [nodes],
  );
  const scopeCount = effectiveRepoIds(repos, scopeRepoIds, selectedRepo).length;

  const [showNodeTypes, setShowNodeTypes] = useState(false);
  const [showEdgeTypes, setShowEdgeTypes] = useState(false);

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

  const toggleNodeType = useCallback((type: string) => {
    setFilteredNodeTypes((prev: string[]) => {
      const next = prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type];
      return next;
    });
  }, [setFilteredNodeTypes]);

  const toggleEdgeType = useCallback((type: string) => {
    setFilteredEdgeTypes((prev: string[]) => {
      const hiding = !prev.includes(type);
      if (hiding && highlightedEdgeTypes.includes(type)) toggleHighlightEdgeType(type);
      return hiding ? [...prev, type] : prev.filter((t) => t !== type);
    });
  }, [setFilteredEdgeTypes, highlightedEdgeTypes, toggleHighlightEdgeType]);

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
              : "Showing the searched node's exact local neighborhood."}
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

      <div>
        <button
          onClick={() => setShowNodeTypes(!showNodeTypes)}
          className="flex items-center gap-1.5 text-2xs font-semibold text-slate-400 uppercase tracking-wider mb-2 hover:text-slate-700 transition-colors w-full"
        >
          <Filter className="w-3 h-3" />
          <span>Node Types{filteredNodeTypes.length > 0 && ` · ${filteredNodeTypes.length} hidden`}</span>
          {showNodeTypes ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
        </button>

        {showNodeTypes && (
          <div className="space-y-1">
            {nodeTypes.map((type) => (
              <label key={type} className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-slate-100 cursor-pointer text-xs transition-colors">
                <input
                  type="checkbox"
                  checked={!filteredNodeTypes.includes(type)}
                  onChange={() => toggleNodeType(type)}
                  className="rounded border-slate-300 text-[#315b47] focus:ring-[#315b47]"
                  style={{ accentColor: "#315b47" }}
                />
                <span className="text-slate-800">{type}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div>
        <button
          onClick={() => setShowEdgeTypes(!showEdgeTypes)}
          className="flex items-center gap-1.5 text-2xs font-semibold text-slate-400 uppercase tracking-wider mb-2 hover:text-slate-700 transition-colors w-full"
        >
          <Filter className="w-3 h-3" />
          <span>Edge Types{filteredEdgeTypes.length > 0 && ` · ${filteredEdgeTypes.length} hidden`}</span>
          {showEdgeTypes ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
        </button>

        {showEdgeTypes && (
          <div className="space-y-1">
            {highlightedEdgeTypes.length > 0 && (
              <button
                onClick={clearHighlightedEdgeTypes}
                className="w-full text-2xs px-2 py-1 rounded-md bg-slate-100
                           text-slate-600 hover:text-slate-900 transition-colors font-medium"
              >
                Clear highlight ({highlightedEdgeTypes.length})
              </button>
            )}
            {edgeTypes.map((type) => {
              const hidden = filteredEdgeTypes.includes(type);
              const lit = highlightedEdgeTypes.includes(type);
              const count = (links as any[]).filter((l) => l.type === type).length;
              return (
                <div key={type} className="flex items-center gap-1">
                  <button
                    onClick={() => toggleHighlightEdgeType(type)}
                    disabled={hidden}
                    aria-pressed={lit}
                    title={hidden ? "Hidden — show it to highlight"
                                  : lit ? "Stop highlighting" : "Highlight these edges"}
                    className={`flex-1 flex items-center gap-2 px-2 py-1 rounded-md text-xs
                                text-left transition-colors disabled:cursor-not-allowed ${
                      lit ? "bg-slate-200 text-slate-900 font-semibold" : "hover:bg-slate-100 text-slate-700"}`}
                    style={{ opacity: hidden ? 0.35 : 1 }}
                  >
                    <span className="w-3.5 h-0.5 rounded-full flex-shrink-0"
                          style={{ background: EDGE_COLORS[type] ?? "#94a3b8" }} />
                    <span className="truncate">{type}</span>
                    <span className="ml-auto text-2xs text-slate-400 font-mono">{count}</span>
                  </button>
                  <button
                    onClick={() => toggleEdgeType(type)}
                    aria-label={hidden ? `Show ${type}` : `Hide ${type}`}
                    title={hidden ? "Show" : "Hide"}
                    className="p-1 rounded text-slate-400 hover:text-slate-700
                               hover:bg-slate-100 transition-colors flex-shrink-0"
                  >
                    {hidden ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
