import { useState, useCallback, useMemo } from "react";
import {
  LayoutGrid, Boxes, Code, Globe, Package, Zap,
  Filter, ChevronDown, ChevronRight, Eye, EyeOff,
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { MODULE_HUE_LIST, moduleOf, EDGE_COLORS } from "@/lib/graphStyle";
import { NODE_TYPES, EDGE_TYPES, VIEW_MODES, type ViewMode } from "@/lib/types";

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
    focusNodeId, setFocusNode, nodes, links,
    highlightedEdgeTypes, toggleHighlightEdgeType, clearHighlightedEdgeTypes,
  } = useGraphStore();

  // Modules present on the canvas, in the same stable order the canvas
  // uses, so legend swatches match the rings they explain.
  const moduleOrder = useMemo(() => {
    const seen = new Set<string>();
    for (const n of nodes as any[]) {
      const key = (n as any).module ?? moduleOf(n.path);
      if (key) seen.add(key);
    }
    return [...seen].sort();
  }, [nodes]);

  const [showNodeTypes, setShowNodeTypes] = useState(false);
  const [showEdgeTypes, setShowEdgeTypes] = useState(false);

  const handleViewModeChange = useCallback((mode: ViewMode) => {
    // Changing the view is a request for the normal graph, not the detour.
    setFocusNode(null);
    setViewMode(mode);
  }, [setViewMode]);

  const toggleNodeType = useCallback((type: string) => {
    setFilteredNodeTypes((prev: string[]) => {
      const next = prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type];
      return next;
    });
  }, [setFilteredNodeTypes]);

  const toggleEdgeType = useCallback((type: string) => {
    setFilteredEdgeTypes((prev: string[]) => {
      const hiding = !prev.includes(type);
      // Hiding a type must drop any highlight on it. Otherwise the highlight
      // count names an edge type that is not drawn, and hiding every lit type
      // dims the entire canvas with nothing emphasised and nothing to explain
      // why.
      if (hiding && highlightedEdgeTypes.includes(type)) toggleHighlightEdgeType(type);
      return hiding ? [...prev, type] : prev.filter((t) => t !== type);
    });
  }, [setFilteredEdgeTypes, highlightedEdgeTypes, toggleHighlightEdgeType]);

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2 flex items-center gap-1.5">
          <LayoutGrid className="w-3 h-3" /> View Mode
        </h4>
        <div className="grid grid-cols-2 gap-1.5">
          {VIEW_MODES.map((mode) => (
            <button
              key={mode}
              onClick={() => handleViewModeChange(mode)}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
                viewMode === mode
                  ? "bg-blue-500/10 text-blue-400 border-blue-500/30"
                  : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 border-transparent"
              }`}
            >
              {VIEW_ICONS[mode]}
              <span className="capitalize">{mode}</span>
            </button>
          ))}
        </div>
      </div>

      {/* A colour encoding nobody can read is decoration. Two channels, two
          jobs: the ring says which MODULE a node belongs to, the magenta line
          says an edge crosses between modules. Module rather than repository,
          because a monorepo's boundaries are inside it. */}
      {moduleOrder.length > 1 && (
        <div className="rounded-lg border border-white/5 bg-black/20 p-2.5 space-y-2">
          <span className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider">
            Reading the graph
          </span>
          <div className="flex items-center gap-2">
            <span className="w-5 rounded-full flex-shrink-0"
                  style={{ background: "#ff5cf0", height: "2.5px" }} />
            <span className="text-2xs text-[#e9ecef]">crosses a module</span>
          </div>
          <div className="space-y-1 pt-1 border-t border-white/5 max-h-40 overflow-y-auto">
            {moduleOrder.map((key, i) => (
              <div key={key} className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full border-2 flex-shrink-0"
                      style={{ borderColor: MODULE_HUE_LIST[i % MODULE_HUE_LIST.length] }} />
                <span className="text-2xs text-[#8c949e] truncate" title={key}>
                  {key.split("/").pop()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {focusNodeId && (
        <div className="rounded-lg border border-blue-500/25 bg-blue-500/10 p-2.5 space-y-2">
          <p className="text-2xs text-blue-200 leading-relaxed">
            A searched node and its neighbourhood have been added to the view.
          </p>
          <button
            onClick={() => setFocusNode(null)}
            className="w-full text-2xs px-2 py-1.5 rounded-md bg-white/5
                       text-[#e9ecef] hover:bg-white/10 transition-colors"
          >
            Reset to the sampled view
          </button>
        </div>
      )}

      {/* Multi-repo only. Several repos' file graphs are disconnected islands
          on their own -- what joins them is a call site INVOKING a contract
          another repo's endpoint EXPOSES. Those bridges are the reason to
          select more than one repo, so they get their own control, and the
          count is stated rather than left to be inferred from the canvas. */}
      {(bridgeCount > 0 || scopeRepoIds.length > 1) && (
        <div className="rounded-lg border border-white/5 bg-black/20 p-2.5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider">
              Cross-module
            </span>
            <span className="text-2xs font-mono text-[#8c949e]">{bridgeCount}</span>
          </div>
          {bridgeCount === 0 ? (
            <p className="text-2xs text-amber-300/90 leading-relaxed">
              No code-level connections between the modules in view. They are
              drawn separately because nothing links them — not because
              anything failed. If you expected links, rebuild them from the
              Service Map.
            </p>
          ) : (
            <>
              <button
                onClick={() => setConnectionsOnly(!connectionsOnly)}
                aria-pressed={connectionsOnly}
                className={`w-full text-2xs px-2 py-1.5 rounded-md transition-colors ${
                  connectionsOnly
                    ? "bg-blue-500/20 text-blue-300"
                    : "bg-white/5 text-[#8c949e] hover:text-[#e9ecef]"}`}
              >
                {connectionsOnly ? "Showing connections only" : "Show connections only"}
              </button>
              <p className="text-2xs text-[#8c949e] leading-relaxed">
                {bridgeCount} call{bridgeCount === 1 ? "" : "s"} cross a module
                boundary, meeting at a shared contract.
              </p>
            </>
          )}
        </div>
      )}

      <div>
        <button
          onClick={() => setShowNodeTypes(!showNodeTypes)}
          className="flex items-center gap-1.5 text-xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2 hover:text-[#e9ecef] transition-colors w-full"
        >
          <Filter className="w-3 h-3" />
          <span>Node Types</span>
          {showNodeTypes ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
        </button>

        {showNodeTypes && (
          <div className="space-y-1" style={{ animation: "fadeIn 0.2s ease-out" }}>
            {NODE_TYPES.map((type) => (
              <label key={type} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-white/5 cursor-pointer text-xs transition-colors">
                <input
                  type="checkbox"
                  checked={!filteredNodeTypes.includes(type)}
                  onChange={() => toggleNodeType(type)}
                />
                <span className="text-[#e9ecef]">{type}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div>
        <button
          onClick={() => setShowEdgeTypes(!showEdgeTypes)}
          className="flex items-center gap-1.5 text-xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2 hover:text-[#e9ecef] transition-colors w-full"
        >
          <Filter className="w-3 h-3" />
          <span>Edge Types</span>
          {showEdgeTypes ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
        </button>

        {showEdgeTypes && (
          <div className="space-y-1" style={{ animation: "fadeIn 0.2s ease-out" }}>
            {/* Two different operations, deliberately separated. Clicking the
                row HIGHLIGHTS: matches keep full strength, the rest recedes,
                nothing is removed — so you see the needle and the haystack
                that gives it meaning. The eye HIDES, which is the older
                filter and destroys that context. They compose. */}
            {highlightedEdgeTypes.length > 0 && (
              <button
                onClick={clearHighlightedEdgeTypes}
                className="w-full text-2xs px-2 py-1 rounded-md bg-white/5
                           text-[#8c949e] hover:text-[#e9ecef] transition-colors"
              >
                Clear highlight ({highlightedEdgeTypes.length})
              </button>
            )}
            {EDGE_TYPES.map((type) => {
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
                    className={`flex-1 flex items-center gap-2 px-2 py-1 rounded text-xs
                                text-left transition-colors disabled:cursor-not-allowed ${
                      lit ? "bg-white/10" : "hover:bg-white/5"}`}
                    style={{ opacity: hidden ? 0.35 : 1 }}
                  >
                    <span className="w-4 h-0.5 rounded-full flex-shrink-0"
                          style={{ background: EDGE_COLORS[type] ?? "#6b7280" }} />
                    <span className={lit ? "text-white font-medium" : "text-[#e9ecef]"}>
                      {type}
                    </span>
                    <span className="ml-auto text-2xs text-[#8c949e] font-mono">{count}</span>
                  </button>
                  <button
                    onClick={() => toggleEdgeType(type)}
                    aria-label={hidden ? `Show ${type}` : `Hide ${type}`}
                    title={hidden ? "Show" : "Hide"}
                    className="p-1 rounded text-[#8c949e] hover:text-[#e9ecef]
                               hover:bg-white/5 transition-colors flex-shrink-0"
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