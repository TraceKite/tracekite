import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { Zap, Loader2, Play, GitMerge } from "lucide-react";
import { getConfidenceStyle, EDGE_COLORS } from "@/lib/graphStyle";
import { isPreviewMode } from "@/lib/previewFixtures";
import ServicePickerModal from "@/components/ServicePickerModal";

function TraceSidebar({ 
  onTrace, tracing, traceError 
}: { 
  onTrace: (f: string, t: string, c: number, a: string, h: number, k: number) => void,
  tracing: boolean,
  traceError: any
}) {
  const { traceData, serviceMapData, scopeRepoIds, traceFrom, traceTo, setTraceEndpoints } =
    useGraphStore();
  const fromSvc = traceFrom;
  const toSvc = traceTo;
  const setFromSvc = (v: string) => setTraceEndpoints(v, traceTo);
  const setToSvc = (v: string) => setTraceEndpoints(traceFrom, v);
  const [minConf, setMinConf] = useState(0.6);
  const [alt, setAlt] = useState<"service" | "code">("service");
  const [maxHops, setMaxHops] = useState(6);
  const [k, setK] = useState(3);

  // Endpoint suggestions, scoped. The scope decides which services you can
  // PICK; it deliberately does not constrain the path the backend walks —
  // filtering intermediate hops would report "no path" whenever a real route
  // passes through an unselected repo, a false negative in the one view whose
  // whole value is trustworthy evidence.
  const services = useMemo(() => {
    const all = (serviceMapData?.nodes ?? []).filter((n: any) => n.kind === "service");
    const inScope = scopeRepoIds.length === 0
      ? all
      : all.filter((n: any) =>
          (n.repo_ids ?? []).some((id: string) => scopeRepoIds.includes(id)));
    return [...new Set(inScope.map((n: any) => n.name as string))].sort();
  }, [serviceMapData, scopeRepoIds]);

  const [pickerTarget, setPickerTarget] = useState<"from" | "to" | null>(null);

  return (
    <aside className="w-80 flex-shrink-0 border-r border-[#2b313a] bg-[#15181c] flex flex-col overflow-hidden z-10 shadow-2xl">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h3 className="text-lg font-bold text-[#e9ecef] flex items-center gap-2 mb-1">
            <Zap className="w-5 h-5 text-violet-400" /> Distributed Trace
          </h3>
          <p className="text-xs text-[#e9ecef] font-medium">How does A reach B, and through which hops?</p>
          <p className="text-2xs text-[#8c949e] mt-1 leading-relaxed">
            One journey, not the whole estate. Ranked paths laid out in hop
            order, every hop backed by a file and line.
          </p>
        </div>

        <div className="space-y-4 bg-black/20 p-4 rounded-xl border border-white/5">
          <div>
            <label className="text-xs font-semibold text-[#aab2bb] block mb-1">Origin Service</label>
            <button
              onClick={() => setPickerTarget("from")}
              className="w-full flex items-center justify-between bg-[#2b313a] border border-white/10 hover:border-violet-500/50 rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={fromSvc ? "text-white font-medium" : "text-[#8c949e]"}>
                {fromSvc || (services[0] ? `e.g. ${services[0]}` : "Select origin service…")}
              </span>
              <span className="text-2xs text-violet-400 font-semibold uppercase shrink-0">Choose</span>
            </button>
          </div>

          <div>
            <label className="text-xs font-semibold text-[#aab2bb] block mb-1">Destination Service</label>
            <button
              onClick={() => setPickerTarget("to")}
              className="w-full flex items-center justify-between bg-[#2b313a] border border-white/10 hover:border-violet-500/50 rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={toSvc ? "text-white font-medium" : "text-[#8c949e]"}>
                {toSvc || (services[1] ? `e.g. ${services[1]}` : "Select destination service…")}
              </span>
              <span className="text-2xs text-violet-400 font-semibold uppercase shrink-0">Choose</span>
            </button>
          </div>

          {pickerTarget && (
            <ServicePickerModal
              title={pickerTarget === "from" ? "Select Origin Service" : "Select Destination Service"}
              selectedService={pickerTarget === "from" ? fromSvc : toSvc}
              onSelect={(serviceName) => {
                if (pickerTarget === "from") setFromSvc(serviceName);
                else setToSvc(serviceName);
              }}
              onClose={() => setPickerTarget(null)}
            />
          )}

          <div className="pt-2 border-t border-white/5 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-2xs font-semibold text-[#8c949e] uppercase">Altitude</label>
              <select value={alt} onChange={(e: any) => setAlt(e.target.value)} className="bg-[#2b313a] text-xs text-white border border-white/10 rounded p-1 outline-none">
                <option value="service">Service</option>
                <option value="code">Code (Crossings)</option>
              </select>
            </div>
            
            <div>
              <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                <span>Min Confidence</span> <span className="text-violet-400">{(minConf*100).toFixed(0)}%</span>
              </div>
              <input type="range" min="0.6" max="1.0" step="0.05" value={minConf} onChange={e => setMinConf(parseFloat(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
            </div>
            
            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                  <span>Max Hops</span> <span className="text-violet-400">{maxHops}</span>
                </div>
                <input type="range" min="1" max="8" step="1" value={maxHops} onChange={e => setMaxHops(parseInt(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
              </div>
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                  <span>Max Paths (k)</span> <span className="text-violet-400">{k}</span>
                </div>
                <input type="range" min="1" max="5" step="1" value={k} onChange={e => setK(parseInt(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
              </div>
            </div>
          </div>

          <button 
            onClick={() => onTrace(fromSvc, toSvc, minConf, alt, maxHops, k)}
            disabled={!fromSvc || !toSvc || tracing}
            className="w-full mt-2 bg-violet-600 hover:bg-violet-500 disabled:bg-violet-900 disabled:opacity-50 text-white font-medium py-2 rounded-lg flex items-center justify-center gap-2 transition-colors"
          >
            {tracing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Trace Paths
          </button>
        </div>

        {traceError?.error === "service_not_found" && (
          <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg mt-4">
            <p className="text-xs text-red-400 font-semibold mb-2">Service not found.</p>
            {traceError.suggestions && traceError.suggestions.length > 0 && (
              <div>
                <p className="text-2xs text-red-300/70 mb-1">Did you mean:</p>
                <div className="flex flex-wrap gap-1">
                  {traceError.suggestions.map((s: string) => (
                    <button key={s} onClick={() => setFromSvc(s)} className="text-2xs bg-red-500/20 px-1.5 py-0.5 rounded text-red-300 hover:bg-red-500/30 transition-colors">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {traceData && traceData.paths && (
          <div className="space-y-3">
            <h4 className="text-xs font-semibold text-[#e9ecef] flex items-center gap-1.5">
              <GitMerge className="w-3.5 h-3.5 text-violet-400" />
              Discovered Paths ({traceData.paths.length})
            </h4>
            {traceData.paths.length === 0 ? (
              <p className="text-xs text-[#8c949e]">No paths found matching constraints.</p>
            ) : (
              traceData.paths.map((p, idx) => (
                <div key={idx} className="bg-[#2b313a]/50 border border-white/5 p-3 rounded-xl hover:bg-[#2b313a] transition-colors cursor-pointer group">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-2xs font-semibold text-[#aab2bb] uppercase">Path #{idx + 1}</span>
                    <span className="text-2xs bg-black/40 text-violet-300 px-1.5 py-0.5 rounded border border-white/5 font-mono">
                      {(p.min_confidence * 100).toFixed(1)}% conf
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1 text-2xs text-[#e9ecef]">
                    {p.nodes.map((n, i) => {
                      // A hop outside the selected repos is shown, not hidden:
                      // the path is real and suppressing it would misreport
                      // reachability. Flag it so the detour is obvious.
                      const outside = scopeRepoIds.length > 0 && !services.includes(n.name);
                      return (
                        <span key={i} className="flex items-center gap-1">
                          <span
                            title={outside ? "Outside the selected repositories" : undefined}
                            className={`px-1.5 py-0.5 rounded truncate max-w-[100px] ${
                              outside
                                ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                : "bg-black/30"}`}>
                            {n.name}
                          </span>
                          {i < p.nodes.length - 1 && <span className="text-[#8c949e]">→</span>}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
}

function TraceCanvasComponent() {
  const { traceData, setSelectedEdge, setSelectedNode, selectedEdge } = useGraphStore();
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [ForceGraphComponent, setForceGraphComponent] = useState<any>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const fgRef = useRef<any>(null);

  useEffect(() => {
    let mounted = true;
    import("react-force-graph-2d").then((mod) => { if (mounted) setForceGraphComponent(() => mod.default); });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!containerEl) return;
    const ro = new ResizeObserver(() => {
      const rect = containerEl.getBoundingClientRect();
      setDimensions({ width: Math.round(rect.width), height: Math.round(rect.height) });
    });
    ro.observe(containerEl);
    return () => ro.disconnect();
  }, [containerEl]);

  const graphData = useMemo(() => {
    if (!traceData) return { nodes: [], links: [] };
    const nodesMap = new Map();
    const linksMap = new Map();
    
    traceData.paths.forEach((path, pathIdx) => {
      path.nodes.forEach((n, hop) => {
        const existing = nodesMap.get(n.id);
        if (!existing) {
          nodesMap.set(n.id, { ...n, pathIndexes: [pathIdx], hop, lanes: [pathIdx] });
        } else {
          existing.pathIndexes.push(pathIdx);
          existing.lanes.push(pathIdx);
          // A node shared by paths of different lengths takes its LATEST hop,
          // so no edge is left pointing backwards through the column order.
          existing.hop = Math.max(existing.hop, hop);
        }
      });
      path.edges.forEach((e, i) => {
        // Backend trace edges are positional: edge i connects nodes[i] -> nodes[i+1].
        const source = path.nodes[i]?.id;
        const target = path.nodes[i + 1]?.id;
        if (!source || !target) return;
        const id = `${source}->${target}->${e.type}`;
        if (!linksMap.has(id)) {
          linksMap.set(id, { ...e, source, target, id, pathIndexes: [pathIdx], crossings: path.crossings });
        } else {
          linksMap.get(id).pathIndexes.push(pathIdx);
        }
      });
    });
    // A trace is an ordered sequence the backend already ranked, so there is
    // nothing for a physics engine to discover. dagMode="lr" only pinned the
    // x-axis and left y to the simulation, which scattered the hops (a middle
    // hop rendered at the bottom of the canvas while its neighbours sat at the
    // top) and reordered parallel paths differently on every run. Place both
    // axes: column = hop index, lane = which path(s) the node belongs to.
    const nodeList = Array.from(nodesMap.values());
    const maxHop = Math.max(1, ...nodeList.map((n: any) => n.hop));
    const laneCount = Math.max(1, traceData.paths.length);
    const colGap = 240;
    const rowGap = 130;
    nodeList.forEach((n: any) => {
      // Shared nodes sit at the mean of the lanes they join, so a common
      // prefix or suffix renders between the paths that share it.
      const lane = n.lanes.reduce((a: number, b: number) => a + b, 0) / n.lanes.length;
      n.fx = (n.hop - maxHop / 2) * colGap;
      n.fy = (lane - (laneCount - 1) / 2) * rowGap;
      n.x = n.fx;
      n.y = n.fy;
    });
    return { nodes: nodeList, links: Array.from(linksMap.values()) };
  }, [traceData]);

  // Every node carries fx/fy now, so there is no layout left to simulate --
  // the forces are neutralised and this effect only frames the result. The
  // retry is still needed because the graph instance does not exist on the
  // first pass.
  useEffect(() => {
    let cancelled = false;
    let tries = 0;
    const apply = () => {
      if (cancelled) return;
      const graph = fgRef.current;
      const charge = graph?.d3Force?.("charge");
      if (!charge) {
        if (tries++ < 25) setTimeout(apply, 80);
        return;
      }
      charge.strength(0);
      graph.d3Force("link")?.strength(0);
      graph.d3Force("center", null);
      setTimeout(() => !cancelled && fgRef.current?.zoomToFit(400, 110), 300);
    };
    apply();
    return () => { cancelled = true; };
  }, [graphData, ForceGraphComponent]);

  const drawNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    // Screen-constant so fitting the path does not inflate the nodes.
    const radius = 10 / globalScale;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = "rgba(139, 92, 246, 0.2)"; // violet
    ctx.fill();
    ctx.strokeStyle = "#8b5cf6";
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();

    // Constant on-screen size; 6px in graph units was illegible at any
    // realistic zoom and changed size as you zoomed.
    const labelSize = 12 / globalScale;
    ctx.font = `600 ${labelSize}px ui-sans-serif, system-ui, sans-serif`;
    const label = node.name;
    const tm = ctx.measureText(label);
    ctx.fillStyle = "rgba(8, 9, 10, 0.9)";
    ctx.beginPath();
    ctx.roundRect(node.x - tm.width / 2 - 3 / globalScale, node.y + radius + 2 / globalScale,
                  tm.width + 6 / globalScale, labelSize * 1.35, 3 / globalScale);
    ctx.fill();

    ctx.fillStyle = "#e9ecef";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, node.x, node.y + radius + 2 / globalScale + labelSize * 0.7);
  }, []);

  const drawLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const start = link.source;
    const end = link.target;
    if (!start || !end || start.x == null || end.x == null) return;

    const color = EDGE_COLORS[link.type] || "#8b5cf6";
    const confStyle = getConfidenceStyle(link.confidence);
    const isSelected = selectedEdge?.id === link.id;

    // Screen-space, matching the nodes — see the note on `radius` above.
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const len = Math.hypot(dx, dy) || 1;
    const gap = 13 / globalScale;
    if (len <= gap * 2) return;
    const sx = start.x + (dx / len) * gap;
    const sy = start.y + (dy / len) * gap;
    const ex = end.x - (dx / len) * gap;
    const ey = end.y - (dy / len) * gap;

    ctx.save();
    ctx.globalAlpha = isSelected ? 1 : confStyle.opacity;

    if (isSelected) {
      ctx.shadowBlur = 8;
      ctx.shadowColor = color;
      ctx.lineWidth = 4 / globalScale;
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
    }

    ctx.strokeStyle = color;
    ctx.lineWidth = (isSelected ? 3 : 1.5) / globalScale;
    ctx.setLineDash(confStyle.dash.map((d: number) => d / globalScale));
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    const angle = Math.atan2(dy, dx);
    const arrLen = (isSelected ? 12 : 8) / globalScale;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - arrLen * Math.cos(angle - Math.PI / 6), ey - arrLen * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(ex - arrLen * Math.cos(angle + Math.PI / 6), ey - arrLen * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }, [selectedEdge]);

  if (!ForceGraphComponent) return null;

  return (
    <div className="absolute inset-0 bg-[#08090a]" ref={setContainerEl}>
      <ForceGraphComponent
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="transparent"
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={() => "replace"}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={() => "replace"}
        // `replace` painting leaves the library guessing at hit areas from
        // nodeVal/linkWidth in graph units; an edge defaulted to a 1-unit line
        // and was effectively unclickable. Both are screen-space here.
        nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, 12 / globalScale, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkPointerAreaPaint={(link: any, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const { source: s, target: t } = link;
          if (!s || !t || s.x == null || t.x == null) return;
          ctx.strokeStyle = color;
          ctx.lineWidth = 10 / globalScale;
          ctx.beginPath();
          ctx.moveTo(s.x, s.y);
          ctx.lineTo(t.x, t.y);
          ctx.stroke();
        }}
        d3VelocityDecay={0.3}
        // No dagMode: it only constrains x and leaves y to the simulation.
        // Both axes are now assigned in the graphData memo.
        // Bound the simulation; the default is 15s of main-thread work.
        cooldownTicks={0}
        // Frame the path once it settles; this was never called, so a trace
        // rendered tiny and off-centre.
        onEngineStop={() => fgRef.current?.zoomToFit(400, 90)}
        onLinkClick={(link: any) => {
          setSelectedEdge(link);
        }}
      />
    </div>
  );
}

export default function TraceView() {
  const { traceData, setTraceData, serviceMapData, setServiceMapData } = useGraphStore();
  const [tracing, setTracing] = useState(false);
  const [traceError, setTraceError] = useState<any>(null);

  // The endpoint suggestions come from the service list, which otherwise only
  // exists after visiting Service Map. Fetch it once if we arrived here first.
  useEffect(() => {
    if (serviceMapData || isPreviewMode()) return;
    api.getServiceMap(0.6).then(setServiceMapData).catch(() => {});
  }, [serviceMapData, setServiceMapData]);

  const handleTrace = async (f: string, t: string, c: number, a: string, h: number, k: number) => {
    setTracing(true);
    setTraceError(null);
    try {
      const data = await api.getTrace(f, t, c, h, k, a);
      setTraceData(data);
    } catch(err: any) {
      try {
        const parsed = JSON.parse(err.message.replace(/^API error \d+: /, ""));
        setTraceError(parsed.detail);
      } catch {
        setTraceError({ error: err.message });
      }
    } finally {
      setTracing(false);
    }
  };

  return (
    <>
      <TraceSidebar onTrace={handleTrace} tracing={tracing} traceError={traceError} />
      <main className="flex-1 relative overflow-hidden bg-slate-950">
        <TraceCanvasComponent />
        {/* Before a trace runs this canvas was simply blank, which is the whole
            reason Trace read as "an empty Service Map". Say what this view is
            for while there is nothing to draw. */}
        {!traceData && !tracing && (
          <div className="absolute inset-0 z-10 flex items-center justify-center px-8">
            <div className="max-w-md text-center space-y-3">
              <Zap className="w-8 h-8 mx-auto text-violet-400/70" />
              <h3 className="text-lg font-bold text-[#e9ecef]">
                How does one service reach another?
              </h3>
              <p className="text-xs leading-relaxed text-[#8c949e]">
                The Service Map shows the whole estate at once. Trace answers a
                narrower question: pick an origin and a destination, and it
                returns the ranked routes between them — laid out in hop order,
                with the file and line behind every hop.
              </p>
              <p className="text-2xs text-[#8c949e]">
                Pick two services on the left, or open the Service Map, select a
                service and choose <span className="text-violet-300">Trace from here</span>.
              </p>
            </div>
          </div>
        )}
      </main>
    </>
  );
}