import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";
import { getConfidenceStyle, EDGE_COLORS } from "@/lib/graphStyle";
import { isPreviewMode } from "@/lib/previewFixtures";
import ServiceMapStatus from "@/components/ServiceMapStatus";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import WorkspaceWarning from "@/components/WorkspaceWarning";
import ServiceMapNavigator from "@/components/ServiceMapNavigator";
import ServiceMapSidebar from "@/components/ServiceMapSidebar";

/* Stable identities: react-kapsule re-applies a prop whenever its reference
 * changes, so inline arrows here re-set the accessor on every React render. */
const nodeReplaceMode = () => "replace" as const;
const linkReplaceMode = () => "replace" as const;

/** On-screen node radius in CSS pixels, before the zoom divide. */
function nodeRadius(node: any): number {
  return node?.is_gateway ? 13 : node?.dead_end ? 6 : 9;
}

function ServiceMapCanvasComponent() {
  const { serviceMapData, setSelectedEdge, selectedEdge, mapEdgeTypes, scopeRepoIds,
          setAppMode, traceFrom, traceTo, setTraceEndpoints,
          highlightedEdgeTypes } = useGraphStore();
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [ForceGraphComponent, setForceGraphComponent] = useState<any>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [hoverNode, setHoverNode] = useState<any>(null);
  const [focusNode, setFocusNode] = useState<any>(null);
  const [layoutReady, setLayoutReady] = useState(false);
  const fgRef = useRef<any>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

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
    if (!serviceMapData) return { nodes: [], links: [], dangling: 0, isolated: 0 };
    // Repo-less rendezvous nodes remain until edge pruning; BUILT_FROM
    // bookkeeping does not become the visual centre of the architecture.
    const inScope = (n: any) => {
      if (scopeRepoIds.length === 0) return true;
      const ids: string[] = n.repo_ids ?? [];
      if (ids.length === 0) return true;
      return ids.some((id) => scopeRepoIds.includes(id));
    };
    const scopedNodes = serviceMapData.nodes.filter(inScope);
    const nodeIds = new Set(scopedNodes.map((n) => n.id));
    const allIds = new Set(serviceMapData.nodes.map((n) => n.id));
    const selected = serviceMapData.edges.filter(
      (e) => e.type !== "BUILT_FROM" && mapEdgeTypes.includes(e.type),
    );
    // Repo-less endpoints need edge attribution to avoid leaking another scope.
    const edgeInScope = (e: any) => {
      if (scopeRepoIds.length === 0) return true;
      const src: string = e.source_repo_id || "";
      if (src) return scopeRepoIds.includes(src);
      return true;
    };
    const links = selected
      .filter(edgeInScope)
      .filter((e: any) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({ ...e, id: `${e.source}->${e.target}->${e.type}` }));
    // Scope filtering is not a dangling-edge data error.
    const dangling = selected.filter(
      (e: any) => !allIds.has(e.source) || !allIds.has(e.target),
    ).length;
    const connected = new Set<string>();
    links.forEach((e: any) => {
      connected.add(typeof e.source === "object" ? e.source.id : e.source);
      connected.add(typeof e.target === "object" ? e.target.id : e.target);
    });
    const retained = scopedNodes.filter((n) => {
        if (connected.has(n.id)) return true;
        if (n.kind !== "service") return false;
        if (scopeRepoIds.length === 0) return true;
        return (n.repo_ids ?? []).some((id: string) => scopeRepoIds.includes(id));
      });
    const isolates = retained.filter((node) => !connected.has(node.id));
    const isolateIndex = new Map(isolates.map((node, index) => [node.id, index]));
    const nodes = retained.map((node) => {
      const index = isolateIndex.get(node.id);
      if (index == null) return { ...node };
      return { ...node, fx: (index - (isolates.length - 1) / 2) * 90, fy: 180 };
    });
    return { nodes, links, dangling, isolated: isolates.length };
  }, [serviceMapData, mapEdgeTypes, scopeRepoIds]);

  useEffect(() => {
    if (focusNode && !graphData.nodes.some((node: any) => node.id === focusNode.id)) {
      setFocusNode(null);
    }
  }, [focusNode, graphData.nodes]);

  // Retry until react-force-graph has created its d3 forces.
  useEffect(() => {
    setLayoutReady(false);
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
      // Repulsion scales with node count: a charge that spreads 200 nodes
      // leaves 9 in a heap, and vice versa.
      const n = Math.max(graphData.nodes.length, 1);
      charge.strength(n < 40 ? -1800 : -600).distanceMax(1200);
      graph.d3Force("link")?.distance(n < 40 ? 220 : 130);
      graph.d3Force("center")?.strength(0.05);
      graph.d3ReheatSimulation?.();
      // Fit after the layout has had time to settle, in case onEngineStop
      // does not fire (it does not when the sim is already cool).
      setTimeout(() => {
        if (cancelled) return;
        fgRef.current?.zoomToFit(400, 90);
        setLayoutReady(true);
      }, 1400);
    };
    apply();
    return () => { cancelled = true; };
  }, [graphData, ForceGraphComponent]);

  /** Edges touching the focused service, split by direction. */
  const focus = useMemo(() => {
    if (!focusNode) return null;
    const idOf = (end: any) => (typeof end === "object" ? end?.id : end);
    const inbound: any[] = [];
    const outbound: any[] = [];
    const neighbors = new Set<string>([focusNode.id]);
    for (const link of graphData.links as any[]) {
      const s = idOf(link.source);
      const t = idOf(link.target);
      if (t === focusNode.id) { inbound.push(link); neighbors.add(s); }
      else if (s === focusNode.id) { outbound.push(link); neighbors.add(t); }
    }
    return { inbound, outbound, neighbors };
  }, [focusNode, graphData]);

  const isDimmed = useCallback((node: any) =>
    !!focus && !focus.neighbors.has(node.id), [focus]);

  const drawNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const isGateway = node.is_gateway;
    const isDeadEnd = node.dead_end;
    const radius = nodeRadius(node) / globalScale;

    ctx.save();
    if (isDimmed(node)) ctx.globalAlpha = 0.12;
    ctx.beginPath();
    
    if (isGateway) {
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i;
        const hx = node.x + radius * Math.cos(angle);
        const hy = node.y + radius * Math.sin(angle);
        if (i === 0) ctx.moveTo(hx, hy);
        else ctx.lineTo(hx, hy);
      }
      ctx.closePath();
      ctx.fillStyle = "rgba(49, 91, 71, 0.15)";
      ctx.fill();
      ctx.strokeStyle = "#315b47";
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    } else if (isDeadEnd) {
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(164, 81, 56, 0.14)";
      ctx.fill();
      ctx.strokeStyle = "#a45138";
      ctx.lineWidth = 1 / globalScale;
      ctx.stroke();
    } else {
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(117, 99, 66, 0.13)";
      ctx.fill();
      ctx.strokeStyle = "#756342";
      ctx.lineWidth = 1.5 / globalScale;
      ctx.stroke();
    }
    
    if (node.scope) {
      const scopeText = node.scope;
      // Screen-space: dividing by globalScale holds the label at a constant
      // on-screen size. At a fixed 4px in GRAPH units this was a smudge at
      // default zoom and grew as you zoomed in — backwards.
      const scopeSize = 10 / globalScale;
      ctx.font = `500 ${scopeSize}px ui-sans-serif, system-ui, sans-serif`;
      const tm = ctx.measureText(scopeText);
      ctx.fillStyle = "#eeeae1";
      ctx.beginPath();
      ctx.roundRect(node.x - tm.width / 2 - 2 / globalScale, node.y - radius - scopeSize * 1.7,
                    tm.width + 4 / globalScale, scopeSize * 1.4, 2 / globalScale);
      ctx.fill();
      ctx.fillStyle = "#6e7168";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(scopeText, node.x, node.y - radius - scopeSize);
    }
    
    const labelSize = 12 / globalScale;
    ctx.font = `600 ${labelSize}px ui-sans-serif, system-ui, sans-serif`;
    const label = node.name;
    const tm = ctx.measureText(label);
    ctx.fillStyle = "rgba(255, 254, 250, 0.96)";
    ctx.beginPath();
    ctx.roundRect(node.x - tm.width / 2 - 3 / globalScale, node.y + radius + 2 / globalScale,
                  tm.width + 6 / globalScale, labelSize * 1.35, 3 / globalScale);
    ctx.fill();
    
    ctx.fillStyle = isDeadEnd ? "#dc2626" : "#1a1d23";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, node.x, node.y + radius + 2 / globalScale + labelSize * 0.7);
    
    ctx.restore();
  }, [isDimmed]);

  const drawLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const start = link.source;
    const end = link.target;
    if (!start || !end || start.x == null || end.x == null) return;

    const color = EDGE_COLORS[link.type] || "#6b6f65";
    const confStyle = getConfidenceStyle(link.confidence);
    const isSelected = selectedEdge?.id === link.id;
    // An edge survives focus only if it actually touches the focused service.
    // Matching on neighbour membership alone would keep edges *between* two
    // neighbours, which are not this service's dependencies.
    const dimLink = !!focus && !(
      focus.inbound.includes(link) || focus.outbound.includes(link));
    // Highlight is independent of node focus: focus narrows by adjacency,
    // highlight narrows by relationship kind. Both dim rather than remove.
    const litType = highlightedEdgeTypes.length === 0
      || highlightedEdgeTypes.includes(link.type);

    // Every length here is screen-space, matching the nodes. A fixed graph-unit
    // gap of 12 was tuned for one zoom level: fitting a small map opened a
    // canyon between the arrowhead and the node, and zooming out buried the
    // arrowhead inside it.
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const len = Math.hypot(dx, dy) || 1;
    const gapStart = (nodeRadius(start) + 3) / globalScale;
    const gapEnd = (nodeRadius(end) + 5) / globalScale;
    if (len <= gapStart + gapEnd) return;
    const sx = start.x + (dx / len) * gapStart;
    const sy = start.y + (dy / len) * gapStart;
    const ex = end.x - (dx / len) * gapEnd;
    const ey = end.y - (dy / len) * gapEnd;

    ctx.save();
    ctx.globalAlpha = (dimLink ? 0.06 : isSelected ? 1 : confStyle.opacity)
      * (litType ? 1 : 0.07);

    if (isSelected) {
      ctx.shadowBlur = 8;
      ctx.shadowColor = color;
      ctx.lineWidth = 4 / globalScale;
      ctx.strokeStyle = "rgba(37,40,33,0.18)";
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
    }

    ctx.strokeStyle = color;
    ctx.lineWidth = (isSelected ? 2.5 : 1.5) / globalScale;
    ctx.setLineDash(confStyle.dash.map((d: number) => d / globalScale));
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    ctx.setLineDash([]);

    const angle = Math.atan2(dy, dx);
    const arrLen = (isSelected ? 10 : 7) / globalScale;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - arrLen * Math.cos(angle - Math.PI / 6), ey - arrLen * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(ex - arrLen * Math.cos(angle + Math.PI / 6), ey - arrLen * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }, [selectedEdge, focus, highlightedEdgeTypes]);

  if (!ForceGraphComponent) return null;

  return (
    <div className="absolute inset-0 bg-[#fbfaf6]" ref={setContainerEl}
      role="application"
      aria-label={`Service map, ${graphData.nodes.length} displayed nodes and ${graphData.links.length} displayed links.`}
      onPointerMove={(e) => {
        if (tooltipRef.current) {
          tooltipRef.current.style.left = `${e.nativeEvent.offsetX}px`;
          tooltipRef.current.style.top = `${e.nativeEvent.offsetY}px`;
        }
      }}
    >
      <ForceGraphComponent
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="transparent"
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={nodeReplaceMode}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={linkReplaceMode}
        // Match hit areas to the screen-space custom paint.
        nodePointerAreaPaint={(node: any, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, Math.max(nodeRadius(node), 10) / globalScale, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkPointerAreaPaint={(link: any, color: string, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const { source: s, target: t } = link;
          if (!s || !t || s.x == null || t.x == null) return;
          ctx.strokeStyle = color;
          ctx.lineWidth = 8 / globalScale;
          ctx.beginPath();
          ctx.moveTo(s.x, s.y);
          ctx.lineTo(t.x, t.y);
          ctx.stroke();
        }}
        d3VelocityDecay={0.3}
        // Bound d3 work instead of using its 15-second default.
        cooldownTicks={220}
        onEngineStop={() => {
          fgRef.current?.zoomToFit(400, 80);
          setLayoutReady(true);
        }}
        onLinkClick={(link: any) => {
          setSelectedEdge(link);
        }}
        // Selecting a service was impossible before this: the canvas hit-tested
        // fine but no handler was wired, so clicking a node did nothing.
        onNodeClick={(node: any) => {
          setFocusNode((current: any) => (current?.id === node.id ? null : node));
        }}
        onBackgroundClick={() => setFocusNode(null)}
        onNodeHover={(node: any) => {
          setHoverNode(node);
          if (typeof document !== "undefined") document.body.style.cursor = node ? "pointer" : "default";
        }}
      />
      {!layoutReady && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#fbfaf6]/90
                        text-xs font-medium text-[#6e7168]">
          Arranging service map…
        </div>
      )}
      {graphData.nodes.length > 0 && <><ServiceMapStatus
        nodeCount={graphData.nodes.length}
        linkCount={graphData.links.length}
        focusedName={focusNode?.name}
        isolatedCount={graphData.isolated}
      />
      <ServiceMapNavigator key={scopeRepoIds.join(",")} nodes={graphData.nodes as any}
        focusedId={focusNode?.id} onSelect={setFocusNode} /></>}
      {graphData.dangling > 0 && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 rounded-md px-3 py-1.5
                        bg-amber-50 border border-amber-200 text-amber-600 text-xs">
          {graphData.dangling} link{graphData.dangling === 1 ? "" : "s"} not drawn — endpoint missing from the response.
        </div>
      )}
      {focusNode && focus && (
        <div className="absolute top-3 right-3 z-30 w-72 max-h-[70%] overflow-y-auto rounded-lg
                        bg-white border border-[#dfe2e8] shadow-lg text-xs">
          <div className="flex items-start justify-between gap-2 p-3 border-b border-[#dfe2e8]">
            <div className="min-w-0">
              <div className="font-bold text-[#1a1d23] truncate">{focusNode.name}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="text-2xs text-[#8b929e] bg-slate-100 px-1.5 py-0.5 rounded">
                  {focusNode.kind}
                </span>
                {focusNode.is_gateway && (
                  <span className="text-2xs text-[#274a3a] bg-[#315b47]/10 px-1.5 py-0.5 rounded">
                    Gateway
                  </span>
                )}
              </div>
              {(focusNode.repo_ids ?? []).length > 0 && (
                <div className="mt-2 text-2xs text-[#8b929e] leading-relaxed">
                  {/* A service joined across repos carries several repo_ids —
                      seeing that here is the clearest signal that cross-repo
                      unification actually happened. */}
                  built from {(focusNode.repo_ids as string[]).join(", ")}
                </div>
              )}
            </div>
            <button onClick={() => setFocusNode(null)}
                    className="shrink-0 text-[#8b929e] hover:text-[#1a1d23] px-1"
                    aria-label="Clear selection">×</button>
          </div>
          {focusNode.kind === "service" && (
            <div className="flex gap-1.5 px-3 py-2 border-b border-[#dfe2e8]">
            <button
              onClick={() => { setTraceEndpoints(focusNode.id, traceTo); setAppMode("trace"); }}
              className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-[#315b47]/10
                         text-[#274a3a] hover:bg-[#315b47]/15 transition-colors">
              Trace from here
            </button>
            <button
              onClick={() => { setTraceEndpoints(traceFrom, focusNode.id); setAppMode("trace"); }}
              className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-[#315b47]/10
                         text-[#274a3a] hover:bg-[#315b47]/15 transition-colors">
              Trace to here
            </button>
            </div>
          )}
          {([["Called by", focus.inbound, "source"],
             ["Calls", focus.outbound, "target"]] as const).map(([label, list, end]) => (
            <div key={label} className="p-3 border-b border-slate-200 last:border-0">
              <div className="uppercase tracking-wider text-2xs text-[#8b929e] mb-1.5">
                {label} ({list.length})
              </div>
              {list.length === 0 ? (
                <div className="text-2xs text-[#5c636d]">nothing recorded</div>
              ) : list.map((link: any, i: number) => {
                const other = link[end];
                const name = typeof other === "object" ? other?.name ?? other?.id : other;
                return (
                  <button key={i} onClick={() => setSelectedEdge(link)}
                          className="w-full text-left py-1 px-1.5 rounded hover:bg-slate-100
                                     flex items-center justify-between gap-2">
                    <span className="truncate text-[#1a1d23]">{name}</span>
                    <span className="shrink-0 text-2xs text-[#8b929e]">
                      {link.confidence != null ? Number(link.confidence).toFixed(2) : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {hoverNode && (
        <div ref={tooltipRef} className="absolute pointer-events-none z-20" style={{ left: 0, top: 0, transform: "translate(-50%, -120%)" }}>
          <div className="rounded-lg px-3 py-2 text-xs space-y-1 bg-white border border-[#dfe2e8] shadow-lg">
            <span className="font-bold text-slate-900 block">{hoverNode.name}</span>
            <span className="text-2xs text-[#8b929e] bg-slate-100 px-1.5 py-0.5 rounded mr-1">{hoverNode.kind}</span>
            {hoverNode.is_gateway && <span className="text-2xs text-[#274a3a] bg-[#315b47]/10 px-1.5 py-0.5 rounded">Gateway</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ServiceMapView() {
  const { serviceMapData, setServiceMapData, setError } = useGraphStore();
  const [minConf, setMinConf] = useState(0.6);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  
  useEffect(() => {
    // Fixture mode already seeded the store; a fetch here can only 401.
    if (isPreviewMode()) return;
    const timer = setTimeout(() => {
      setLoading(true);
      setLoadError(null);
      api.getServiceMap(minConf)
        .then(setServiceMapData)
        .catch(err => { setLoadError(err.message); setError(err.message); })
        .finally(() => setLoading(false));
    }, 500);
    return () => clearTimeout(timer);
  }, [minConf, setServiceMapData, setError]);

  return (
    <>
      <ServiceMapSidebar minConf={minConf} setMinConf={setMinConf} />
      <main className="flex-1 relative overflow-hidden bg-[#fbfaf6]">
        <ServiceMapCanvasComponent />
        {loadError && !serviceMapData && (
          <GraphCanvasMessage title="Service map unavailable" detail={loadError} warning />
        )}
        {loadError && serviceMapData && (
          <WorkspaceWarning message={loadError} onDismiss={() => setLoadError(null)} />
        )}
        {loading && (
          <div className="absolute top-4 right-4 bg-white/90 border border-[#dfe2e8] px-3 py-1.5 rounded-lg flex items-center gap-2 shadow-sm z-10">
            <Loader2 className="w-3 h-3 text-[#315b47] animate-spin" />
            <span className="text-xs text-slate-900">Loading map...</span>
          </div>
        )}
      </main>
    </>
  );
}
