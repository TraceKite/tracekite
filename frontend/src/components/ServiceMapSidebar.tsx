import { useEffect, useMemo } from "react";
import { Eye, EyeOff, Loader2, Network, RefreshCw, ShieldAlert } from "lucide-react";

import { api } from "@/lib/api";
import { EDGE_COLORS, MAP_EDGE_LEGEND } from "@/lib/graphStyle";
import { isPreviewMode } from "@/lib/previewFixtures";
import { projectServiceMap } from "@/lib/serviceMapProjection";
import { useGraphStore } from "@/store/graphStore";
import SidebarPanel from "@/components/SidebarPanel";

export default function ServiceMapSidebar({ minConf, setMinConf }: { minConf: number, setMinConf: (n: number) => void }) {
  const { serviceMapData, linkerStatus, setLinkerStatus, mapEdgeTypes,
          toggleMapEdgeType, scopeRepoIds, highlightedEdgeTypes,
          toggleHighlightEdgeType, clearHighlightedEdgeTypes,
          ingestionJob, setIngestionJob, setError } = useGraphStore();
  const linkJobActive = ingestionJob?.repo_id === "__linker__"
    && ["queued", "running"].includes(ingestionJob.status);
  const linkRunActive = linkerStatus?.latest?.status === "running";
  const rebuilding = linkJobActive || linkRunActive;

  useEffect(() => {
    if (isPreviewMode()) return;
    api.getLinkerStatus().then(setLinkerStatus).catch(console.error);
    const interval = setInterval(() => {
      api.getLinkerStatus().then(setLinkerStatus).catch(() => {});
    }, rebuilding ? 1500 : 10000);
    return () => clearInterval(interval);
  }, [rebuilding, setLinkerStatus]);

  const handleRebuild = async () => {
    try {
      const result = await api.rebuildLinks();
      const now = new Date().toISOString();
      setIngestionJob({
        job_id: result.job_id, repo_id: "__linker__", status: "queued",
        progress: 0, message: "Link rebuild queued", error: null,
        created_at: now, updated_at: now,
      });
    } catch(err: any) {
      setError(err.message);
    }
  };

  const isStale = linkerStatus?.warnings.some(w => w.kind === 'links_stale');

  const scopedProjection = useMemo(
    () => projectServiceMap(serviceMapData, mapEdgeTypes, scopeRepoIds),
    [mapEdgeTypes, serviceMapData, scopeRepoIds],
  );
  const scopedServices = scopedProjection.nodes.filter(
    (node) => node.kind === "service").length;
  const scopedLinks = scopedProjection.links.length;

  return (
    <SidebarPanel label="Service map">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h3 className="text-lg font-bold text-[#1a1d23] flex items-center gap-2 mb-1">
            <Network className="w-5 h-5 text-[#315b47]" /> Service Map
          </h3>
          <p className="text-xs text-[#1a1d23] font-medium">What exists, and what talks to what?</p>
          <p className="text-2xs text-[#8b929e] mt-1 leading-relaxed">
            The selected repository scope. Select a service to see callers and
            callees, then continue into a trace.
          </p>
        </div>

        {(isStale || rebuilding) && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-amber-600">
                  {rebuilding ? "Rebuilding links" : "Links are stale"}
                </p>
                <p className="text-2xs text-amber-600 mt-1 mb-2">
                  {rebuilding
                    ? "TraceKite is rebuilding relationships automatically. The map updates when it completes."
                    : "New code was ingested since the map was last built. Some relationships might be missing."}
                </p>
                <button 
                  onClick={handleRebuild}
                  disabled={rebuilding}
                  className="text-2xs font-medium bg-amber-100 hover:bg-amber-200 text-amber-700 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
                >
                  {rebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                  {rebuilding ? "Rebuilding…" : "Rebuild Links"}
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <label className="text-xs font-semibold text-[#8b929e] uppercase tracking-wider flex justify-between">
            <span>Min Confidence</span>
            <span className="text-[#315b47] font-mono">{(minConf * 100).toFixed(0)}%</span>
          </label>
          <input 
            type="range" 
            min="0.6" max="1.0" step="0.05" 
            value={minConf} 
            onChange={e => setMinConf(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-[#315b47]"
          />
          <div className="flex justify-between text-2xs text-[#8b929e]">
            <span>More Results</span>
            <span>Higher Certainty</span>
          </div>
        </div>

        {serviceMapData && (
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-center">
              <p className="text-xl font-semibold text-[#1a1d23]">{scopedServices}</p>
              <p className="text-2xs text-[#8b929e] uppercase tracking-wider mt-1">
                Services{scopeRepoIds.length > 0 && ` of ${serviceMapData.totals.services}`}
              </p>
            </div>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-center">
              <p className="text-xl font-semibold text-[#1a1d23]">{scopedLinks}</p>
              <p className="text-2xs text-[#8b929e] uppercase tracking-wider mt-1">
                Link candidates
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2">
          <label className="text-2xs font-semibold text-[#8b929e] uppercase tracking-wider">
            Relations shown
          </label>
          {highlightedEdgeTypes.length > 0 && (
            <button
              onClick={clearHighlightedEdgeTypes}
              className="w-full text-2xs px-2 py-1 rounded-md bg-slate-100
                         text-[#5c6370] hover:text-[#1a1d23] transition-colors"
            >
              Clear highlight ({highlightedEdgeTypes.length})
            </button>
          )}
          <div className="space-y-1">
            {MAP_EDGE_LEGEND.map(({ type, label }) => {
              const on = mapEdgeTypes.includes(type);
              const lit = highlightedEdgeTypes.includes(type);
              const count = scopedProjection.links.filter(
                (edge) => edge.type === type).length;
              return (
                <div key={type} className="flex items-center gap-1">
                  <button
                    onClick={() => toggleHighlightEdgeType(type)}
                    disabled={!on}
                    aria-pressed={lit}
                    title={!on ? "Hidden — show it to highlight"
                               : lit ? "Stop highlighting" : "Highlight these edges"}
                    className={`flex-1 flex items-center gap-2 px-2 py-1.5 rounded-md text-left
                                transition-colors disabled:cursor-not-allowed ${
                      lit ? "bg-slate-200" : "hover:bg-slate-100"}`}
                    style={{ opacity: on ? 1 : 0.45 }}
                  >
                    <span className="w-4 h-0.5 rounded-full flex-shrink-0"
                          style={{ background: EDGE_COLORS[type] ?? "#8b929e" }} />
                    <span className={`text-xs flex-1 ${lit ? "text-[#1a1d23] font-medium" : "text-[#1a1d23]"}`}>
                      {label}
                    </span>
                    <span className="text-2xs text-[#8b929e] font-mono">{count}</span>
                  </button>
                  <button
                    onClick={() => {
                      if (on && highlightedEdgeTypes.includes(type)) toggleHighlightEdgeType(type);
                      toggleMapEdgeType(type);
                    }}
                    aria-label={on ? `Hide ${label}` : `Show ${label}`}
                    title={on ? "Hide" : "Show"}
                    className="p-1 rounded text-[#8b929e] hover:text-[#1a1d23]
                               hover:bg-slate-100 transition-colors flex-shrink-0"
                  >
                    {on ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                  </button>
                </div>
              );
            })}
          </div>
          <p className="text-2xs text-[#8b929e] leading-relaxed">
            Repository build edges are hidden — they are bookkeeping, not architecture.
          </p>
        </div>
      </div>
    </SidebarPanel>
  );
}
