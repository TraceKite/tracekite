import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { ShieldAlert, RefreshCw, Layers, Loader2, Network, Eye, EyeOff } from "lucide-react";
import { getConfidenceColor, getConfidenceStyle, EDGE_COLORS, MAP_EDGE_LEGEND } from "@/lib/graphStyle";
import EmptyState from "./EmptyState";
import { isPreviewMode } from "@/lib/previewFixtures";

function ServiceMapSidebar({ minConf, setMinConf }: { minConf: number, setMinConf: (n: number) => void }) {
  const { serviceMapData, linkerStatus, setLinkerStatus, mapEdgeTypes,
          toggleMapEdgeType, scopeRepoIds, highlightedEdgeTypes,
          toggleHighlightEdgeType, clearHighlightedEdgeTypes } = useGraphStore();
  const [rebuilding, setRebuilding] = useState(false);

  useEffect(() => {
    if (isPreviewMode()) return;
    api.getLinkerStatus().then(setLinkerStatus).catch(console.error);
    const interval = setInterval(() => {
      api.getLinkerStatus().then(setLinkerStatus).catch(() => {});
    }, 10000);
    return () => clearInterval(interval);
  }, [setLinkerStatus]);

  const handleRebuild = async () => {
    setRebuilding(true);
    try {
      await api.rebuildLinks();
      setTimeout(() => api.getLinkerStatus().then(setLinkerStatus), 2000);
    } catch(err) {
      console.error(err);
    } finally {
      setTimeout(() => setRebuilding(false), 2000);
    }
  };

  const isStale = linkerStatus?.warnings.some(w => w.kind === 'links_stale');

  const scopedServices = useMemo(() => {
    if (!serviceMapData) return 0;
    const services = serviceMapData.nodes.filter((n: any) => n.kind === "service");
    if (scopeRepoIds.length === 0) return services.length;
    return services.filter((n: any) =>
      (n.repo_ids ?? []).some((id: string) => scopeRepoIds.includes(id))).length;
  }, [serviceMapData, scopeRepoIds]);

  // Reporting the estate-wide edge total while a scope is active would claim
  // credit for links the canvas is not drawing.
  const scopedLinks = useMemo(() => {
    if (!serviceMapData) return 0;
    if (scopeRepoIds.length === 0) return serviceMapData.totals.edges;
    return serviceMapData.edges.filter((e: any) => {
      const src: string = e.source_repo_id || "";
      return src ? scopeRepoIds.includes(src) : true;
    }).length;
  }, [serviceMapData, scopeRepoIds]);

  return (
    <aside className="w-72 flex-shrink-0 border-r border-[#2b313a] bg-[#15181c] flex flex-col overflow-hidden z-10 shadow-2xl">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h3 className="text-lg font-bold text-[#e9ecef] flex items-center gap-2 mb-1">
            <Network className="w-5 h-5 text-emerald-400" /> Service Map
          </h3>
          <p className="text-xs text-[#e9ecef] font-medium">What exists, and what talks to what?</p>
          <p className="text-2xs text-[#8c949e] mt-1 leading-relaxed">
            The whole estate at once. Select a service to see who calls it, or
            jump from there into a trace.
          </p>
        </div>

        {isStale && (
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-3">
            <div className="flex items-start gap-2">
              <ShieldAlert className="w-4 h-4 text-amber-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-amber-400">Links are stale</p>
                <p className="text-2xs text-amber-500/80 mt-1 mb-2">New code was ingested since the map was last built. Some relationships might be missing.</p>
                <button 
                  onClick={handleRebuild}
                  disabled={rebuilding}
                  className="text-2xs font-medium bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
                >
                  {rebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} 
                  Rebuild Links
                </button>
              </div>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <label className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider flex justify-between">
            <span>Min Confidence</span>
            <span className="text-emerald-400 font-mono">{(minConf * 100).toFixed(0)}%</span>
          </label>
          <input 
            type="range" 
            min="0.6" max="1.0" step="0.05" 
            value={minConf} 
            onChange={e => setMinConf(parseFloat(e.target.value))}
            className="w-full h-1.5 bg-[#2b313a] rounded-lg appearance-none cursor-pointer accent-emerald-500"
          />
          <div className="flex justify-between text-2xs text-[#8c949e]">
            <span>More Results</span>
            <span>Higher Certainty</span>
          </div>
        </div>

        {serviceMapData && (
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-black/20 border border-white/5 rounded-lg p-3 text-center">
              <p className="text-xl font-semibold text-[#e9ecef]">{scopedServices}</p>
              <p className="text-2xs text-[#8c949e] uppercase tracking-wider mt-1">
                Services{scopeRepoIds.length > 0 && ` of ${serviceMapData.totals.services}`}
              </p>
            </div>
            <div className="bg-black/20 border border-white/5 rounded-lg p-3 text-center">
              <p className="text-xl font-semibold text-[#e9ecef]">{scopedLinks}</p>
              <p className="text-2xs text-[#8c949e] uppercase tracking-wider mt-1">
                Links{scopeRepoIds.length > 0 && ` of ${serviceMapData.totals.edges}`}
              </p>
            </div>
          </div>
        )}

        {/* Legend + relation filter. The map previously drew four edge types
            in unexplained colours with no key at all — two of them (publish
            and consume) in near-identical reds. Routing, calls and messaging
            are different relations; superimposing them on one canvas is a
            documented way to make a graph unreadable, so they are separable. */}
        <div className="space-y-2">
          <label className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">
            Relations shown
          </label>
          {/* Same two operations as the Repo view's edge list, because it is
              the same concept: clicking highlights, the eye hides. Leaving
              this list filter-only would have meant one control behaving two
              different ways depending on which tab you were on. */}
          {highlightedEdgeTypes.length > 0 && (
            <button
              onClick={clearHighlightedEdgeTypes}
              className="w-full text-2xs px-2 py-1 rounded-md bg-white/5
                         text-[#8c949e] hover:text-[#e9ecef] transition-colors"
            >
              Clear highlight ({highlightedEdgeTypes.length})
            </button>
          )}
          <div className="space-y-1">
            {MAP_EDGE_LEGEND.map(({ type, label }) => {
              const on = mapEdgeTypes.includes(type);
              const lit = highlightedEdgeTypes.includes(type);
              const count = serviceMapData?.edges.filter(e => e.type === type).length ?? 0;
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
                      lit ? "bg-white/10" : "hover:bg-white/5"}`}
                    style={{ opacity: on ? 1 : 0.45 }}
                  >
                    <span className="w-4 h-0.5 rounded-full flex-shrink-0"
                          style={{ background: EDGE_COLORS[type] ?? "#8c949e" }} />
                    <span className={`text-xs flex-1 ${lit ? "text-white font-medium" : "text-[#e9ecef]"}`}>
                      {label}
                    </span>
                    <span className="text-2xs text-[#8c949e] font-mono">{count}</span>
                  </button>
                  <button
                    onClick={() => {
                      if (on && highlightedEdgeTypes.includes(type)) toggleHighlightEdgeType(type);
                      toggleMapEdgeType(type);
                    }}
                    aria-label={on ? `Hide ${label}` : `Show ${label}`}
                    title={on ? "Hide" : "Show"}
                    className="p-1 rounded text-[#8c949e] hover:text-[#e9ecef]
                               hover:bg-white/5 transition-colors flex-shrink-0"
                  >
                    {on ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
                  </button>
                </div>
              );
            })}
          </div>
          <p className="text-2xs text-[#8c949e] leading-relaxed">
            Repository build edges are hidden — they are bookkeeping, not architecture.
          </p>
        </div>
      </div>
    </aside>
  );
}

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
    if (!serviceMapData) return { nodes: [], links: [], dangling: 0 };
    // BUILT_FROM is Service->Repo bookkeeping, and on the live estate it was
    // 28 of 67 edges — 42% of the picture, arranged as two stars around the
    // repo nodes, which dominated the layout and buried the architecture.
    // Repos remain reachable from a service; they are just not drawn as the
    // centre of gravity of the map.
    // An edge whose endpoint is absent from `nodes` makes the layout engine
    // abandon link binding at that index, so ONE dangling edge silently drops
    // every edge after it — three of eight rendered, and nothing said so.
    // Drop them here deliberately, and count them so the loss is visible.
    // Repo scope. A service joined across repos carries several repo_ids, so
    // "in scope" is any overlap — otherwise selecting one petclinic repo would
    // hide the very services that prove the cross-repo join. Rendezvous nodes
    // (Topic, ServiceName, HttpContract) carry no repo_ids at all; they are
    // kept and pruned later only if nothing in scope still connects to them.
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
    // An edge between two repo-LESS rendezvous nodes (File -> Topic) passes a
    // node-only scope test on both ends, which is how selecting one repo still
    // drew another repo's Kafka example files. Judge such edges by their own
    // source_repo_id instead.
    const edgeInScope = (e: any) => {
      if (scopeRepoIds.length === 0) return true;
      const src: string = e.source_repo_id || "";
      if (src) return scopeRepoIds.includes(src);
      return true; // no attribution: fall back to the endpoint test below
    };
    const links = selected
      .filter(edgeInScope)
      .filter((e: any) => nodeIds.has(e.source) && nodeIds.has(e.target))
      .map((e) => ({ ...e, id: `${e.source}->${e.target}->${e.type}` }));
    // Only count an edge as dangling when its endpoint is missing from the
    // RESPONSE — an edge hidden because a repo is out of scope is the filter
    // working, not a data error, and must not raise the warning banner.
    const dangling = selected.filter(
      (e: any) => !allIds.has(e.source) || !allIds.has(e.target),
    ).length;
    const connected = new Set<string>();
    links.forEach((e: any) => {
      connected.add(typeof e.source === "object" ? e.source.id : e.source);
      connected.add(typeof e.target === "object" ? e.target.id : e.target);
    });
    // Unconnected nodes have no attractive force and drift into a shell that
    // never settles; keep services (the subject of the view) and drop orphan
    // repo/name nodes that only existed to terminate a BUILT_FROM edge.
    const nodes = scopedNodes
      .filter((n) => {
        if (connected.has(n.id)) return true;
        if (n.kind !== "service") return false;
        if (scopeRepoIds.length === 0) return true;
        // A service with no repo_ids passed the scope test by DEFAULT, not by
        // belonging. Keeping it while a scope is active drew three services
        // from an unrelated estate, disconnected, inside a view scoped to
        // petclinic — and made the canvas disagree with the sidebar, which
        // counts only services that genuinely overlap the scope.
        return (n.repo_ids ?? []).some((id: string) => scopeRepoIds.includes(id));
      })
      .map((n) => ({ ...n }));
    return { nodes, links, dangling };
  }, [serviceMapData, mapEdgeTypes, scopeRepoIds]);

  // Apply forces through the ref — as a prop, `d3Force` is silently discarded.
  // The forces do not exist until the graph instance has initialised, which
  // happens after this effect first runs, so a single attempt silently does
  // nothing and the graph keeps d3's defaults (charge -30) — a tight clump.
  // Retry until the instance is actually there.
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
      // Repulsion scales with node count: a charge that spreads 200 nodes
      // leaves 9 in a heap, and vice versa.
      const n = Math.max(graphData.nodes.length, 1);
      charge.strength(n < 40 ? -1800 : -600).distanceMax(1200);
      graph.d3Force("link")?.distance(n < 40 ? 220 : 130);
      graph.d3Force("center")?.strength(0.05);
      graph.d3ReheatSimulation?.();
      // Fit after the layout has had time to settle, in case onEngineStop
      // does not fire (it does not when the sim is already cool).
      setTimeout(() => !cancelled && fgRef.current?.zoomToFit(400, 90), 1400);
    };
    apply();
    return () => { cancelled = true; };
  }, [graphData, ForceGraphComponent]);

  /** Edges touching the focused service, split by direction.
   *
   * The map is ~100 services and ~250 edges, so "what talks to this?" is not
   * answerable by looking. Both lists come from data already on the client —
   * no request — and each row carries the edge itself, so selecting one opens
   * the same evidence drawer a click on the line would. */
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
    // Screen-constant, like the labels. In graph units a node inflates as you
    // zoom, so fitting a small graph turned 9 services into giant discs that
    // overlapped each other and their own labels.
    const radius = nodeRadius(node) / globalScale;

    ctx.save();
    // Dim rather than hide: the shape of the whole estate stays visible, so
    // you can see where the focused service sits in it.
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
      ctx.fillStyle = "rgba(16, 185, 129, 0.2)";
      ctx.fill();
      ctx.strokeStyle = "#10b981";
      ctx.lineWidth = 2 / globalScale;
      ctx.stroke();
    } else if (isDeadEnd) {
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(239, 68, 68, 0.2)";
      ctx.fill();
      ctx.strokeStyle = "#ef4444";
      ctx.lineWidth = 1 / globalScale;
      ctx.stroke();
    } else {
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = "rgba(59, 130, 246, 0.2)";
      ctx.fill();
      ctx.strokeStyle = "#3b82f6";
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
      ctx.fillStyle = "#1c2026";
      ctx.beginPath();
      ctx.roundRect(node.x - tm.width / 2 - 2 / globalScale, node.y - radius - scopeSize * 1.7,
                    tm.width + 4 / globalScale, scopeSize * 1.4, 2 / globalScale);
      ctx.fill();
      ctx.fillStyle = "#aab2bb";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(scopeText, node.x, node.y - radius - scopeSize);
    }
    
    const labelSize = 12 / globalScale;
    ctx.font = `600 ${labelSize}px ui-sans-serif, system-ui, sans-serif`;
    const label = node.name;
    const tm = ctx.measureText(label);
    ctx.fillStyle = "rgba(8, 9, 10, 0.82)";
    ctx.beginPath();
    ctx.roundRect(node.x - tm.width / 2 - 3 / globalScale, node.y + radius + 2 / globalScale,
                  tm.width + 6 / globalScale, labelSize * 1.35, 3 / globalScale);
    ctx.fill();
    
    ctx.fillStyle = isDeadEnd ? "#fca5a5" : "#e9ecef";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, node.x, node.y + radius + 2 / globalScale + labelSize * 0.7);
    
    ctx.restore();
  }, [isDimmed]);

  const drawLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const start = link.source;
    const end = link.target;
    if (!start || !end || start.x == null || end.x == null) return;

    const color = EDGE_COLORS[link.type] || "#3b82f6";
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
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
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
    <div className="absolute inset-0 bg-[#08090a]" ref={setContainerEl}
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
        // With `replace` painting, the library falls back to a hit area derived
        // from nodeVal/linkWidth in GRAPH units, which no longer matches what is
        // drawn. Edges in particular defaulted to a 1-unit line — effectively
        // unclickable. Both hit areas are screen-space, with a floor so small
        // targets stay reachable.
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
        // Without this the library runs its default `cooldownTime` of 15000ms:
        // fifteen seconds of main-thread d3-force (a full quadtree rebuild per
        // tick) regardless of graph size. d3-force converges in ~300 ticks, and
        // this estate is 56 nodes, so it settles in a fraction of a second.
        cooldownTicks={220}
        // The map never framed itself: fgRef was assigned and never read, so
        // the graph rendered at default zoom around the origin — a small
        // clump in the middle of an otherwise empty canvas. Fit once the
        // simulation settles.
        onEngineStop={() => fgRef.current?.zoomToFit(400, 80)}
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
      {graphData.dangling > 0 && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 rounded-md px-3 py-1.5
                        bg-amber-500/10 border border-amber-500/25 text-amber-300 text-xs">
          {graphData.dangling} link{graphData.dangling === 1 ? "" : "s"} not drawn — endpoint missing from the response.
        </div>
      )}
      {focusNode && focus && (
        <div className="absolute top-3 right-3 z-30 w-72 max-h-[70%] overflow-y-auto rounded-lg
                        bg-[#11151b]/95 border border-white/10 backdrop-blur-md text-xs">
          <div className="flex items-start justify-between gap-2 p-3 border-b border-white/10">
            <div className="min-w-0">
              <div className="font-bold text-[#e9ecef] truncate">{focusNode.name}</div>
              <div className="mt-1 flex flex-wrap gap-1">
                <span className="text-2xs text-[#8c949e] bg-[#2b313a] px-1.5 py-0.5 rounded">
                  {focusNode.kind}
                </span>
                {focusNode.is_gateway && (
                  <span className="text-2xs text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
                    Gateway
                  </span>
                )}
              </div>
              {(focusNode.repo_ids ?? []).length > 0 && (
                <div className="mt-2 text-2xs text-[#8c949e] leading-relaxed">
                  {/* A service joined across repos carries several repo_ids —
                      seeing that here is the clearest signal that cross-repo
                      unification actually happened. */}
                  built from {(focusNode.repo_ids as string[]).join(", ")}
                </div>
              )}
            </div>
            <button onClick={() => setFocusNode(null)}
                    className="shrink-0 text-[#8c949e] hover:text-white px-1"
                    aria-label="Clear selection">×</button>
          </div>
          {/* The map answers "what talks to what". The moment you care about a
              particular service, the next question is "how does it reach X" —
              which is Trace. Handing the service straight over makes Trace the
              second step of one flow rather than a rival view you have to set
              up again from scratch. */}
          <div className="flex gap-1.5 px-3 py-2 border-b border-white/10">
            <button
              onClick={() => { setTraceEndpoints(focusNode.name, traceTo); setAppMode("trace"); }}
              className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-violet-500/15
                         text-violet-300 hover:bg-violet-500/25 transition-colors">
              Trace from here
            </button>
            <button
              onClick={() => { setTraceEndpoints(traceFrom, focusNode.name); setAppMode("trace"); }}
              className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-violet-500/15
                         text-violet-300 hover:bg-violet-500/25 transition-colors">
              Trace to here
            </button>
          </div>
          {([["Called by", focus.inbound, "source"],
             ["Calls", focus.outbound, "target"]] as const).map(([label, list, end]) => (
            <div key={label} className="p-3 border-b border-white/5 last:border-0">
              <div className="uppercase tracking-wider text-2xs text-[#8c949e] mb-1.5">
                {label} ({list.length})
              </div>
              {list.length === 0 ? (
                <div className="text-2xs text-[#5c636d]">nothing recorded</div>
              ) : list.map((link: any, i: number) => {
                const other = link[end];
                const name = typeof other === "object" ? other?.name ?? other?.id : other;
                return (
                  <button key={i} onClick={() => setSelectedEdge(link)}
                          className="w-full text-left py-1 px-1.5 rounded hover:bg-white/10
                                     flex items-center justify-between gap-2">
                    <span className="truncate text-[#e9ecef]">{name}</span>
                    <span className="shrink-0 text-2xs text-[#8c949e]">
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
          <div className="rounded-lg px-3 py-2 text-xs space-y-1 bg-black/80 border border-white/10 backdrop-blur-md">
            <span className="font-bold text-white block">{hoverNode.name}</span>
            <span className="text-2xs text-[#8c949e] bg-[#2b313a] px-1.5 py-0.5 rounded mr-1">{hoverNode.kind}</span>
            {hoverNode.is_gateway && <span className="text-2xs text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">Gateway</span>}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ServiceMapView() {
  const { setServiceMapData, setError } = useGraphStore();
  const [minConf, setMinConf] = useState(0.6);
  const [loading, setLoading] = useState(false);
  
  useEffect(() => {
    // Fixture mode already seeded the store; a fetch here can only 401.
    if (isPreviewMode()) return;
    const timer = setTimeout(() => {
      setLoading(true);
      api.getServiceMap(minConf)
        .then(setServiceMapData)
        .catch(err => setError(err.message))
        .finally(() => setLoading(false));
    }, 500);
    return () => clearTimeout(timer);
  }, [minConf, setServiceMapData, setError]);

  return (
    <>
      <ServiceMapSidebar minConf={minConf} setMinConf={setMinConf} />
      <main className="flex-1 relative overflow-hidden bg-slate-950">
        <ServiceMapCanvasComponent />
        {loading && (
          <div className="absolute top-4 right-4 bg-black/50 border border-white/10 px-3 py-1.5 rounded-lg flex items-center gap-2 backdrop-blur-sm z-10">
            <Loader2 className="w-3 h-3 text-emerald-400 animate-spin" />
            <span className="text-xs text-white">Loading map...</span>
          </div>
        )}
      </main>
    </>
  );
}
