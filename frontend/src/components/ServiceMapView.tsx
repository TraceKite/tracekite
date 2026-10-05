import { useEffect, useState, useRef, useMemo, useCallback } from "react";
import { useGraphStore } from "@/store/graphStore";
import { Loader2 } from "lucide-react";
import { getConfidenceStyle, EDGE_COLORS } from "@/lib/graphStyle";
import ServiceMapStatus from "@/components/ServiceMapStatus";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import WorkspaceWarning from "@/components/WorkspaceWarning";
import ServiceMapNavigator from "@/components/ServiceMapNavigator";
import ServiceMapSidebar from "@/components/ServiceMapSidebar";
import { serviceMapEmptyState } from "@/lib/serviceMapProjection";
import { serviceDisplayNames } from "@/lib/serviceMapLabel";
import {
  nodeRadius, paintServiceLabel, paintServiceLink, paintServiceNode,
} from "@/lib/serviceMapPainter";
import { useServiceMapLabels } from "@/hooks/useServiceMapLabels";
import { useServiceMapLayout } from "@/hooks/useServiceMapLayout";
import { useServiceMapData } from "@/hooks/useServiceMapData";
import ServiceMapFocusPanel from "@/components/ServiceMapFocusPanel";

/* Stable identities: react-kapsule re-applies a prop whenever its reference
 * changes, so inline arrows here re-set the accessor on every React render. */
const nodeReplaceMode = () => "replace" as const;
const linkReplaceMode = () => "replace" as const;

function ServiceMapCanvasComponent() {
  const { serviceMapData, setSelectedEdge, selectedEdge, mapEdgeTypes, scopeRepoIds,
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

  const { graphData, layoutReady, onEngineStop } = useServiceMapLayout({
    graphRef: fgRef, graphLoaded: !!ForceGraphComponent, data: serviceMapData,
    mapEdgeTypes, scopeRepoIds, dimensions,
  });
  const emptyState = useMemo(
    () => serviceMapEmptyState(serviceMapData, graphData, scopeRepoIds),
    [serviceMapData, graphData, scopeRepoIds],
  );
  // Ambiguity depends on which nodes are drawn together, so this is derived
  // from the projected set rather than baked into the node on the way in.
  const displayNames = useMemo(
    () => serviceDisplayNames(graphData.nodes), [graphData.nodes]);
  useEffect(() => {
    if (focusNode && !graphData.nodes.some((node: any) => node.id === focusNode.id)) {
      setFocusNode(null);
    }
  }, [focusNode, graphData.nodes]);

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
  const { beginFrame, placedLabel } = useServiceMapLabels(graphData, displayNames,
    { focusId: focusNode?.id, hoverId: hoverNode?.id, lit: focus?.neighbors ?? null });

  const drawNode = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const dimmed = isDimmed(node);
    paintServiceNode(node, ctx, globalScale, { dimmed });
    const pill = placedLabel(node, ctx, globalScale);
    if (pill) paintServiceLabel(node, ctx, globalScale, { pill, dimmed });
  }, [isDimmed, placedLabel]);

  const drawLink = useCallback((link: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const confStyle = getConfidenceStyle(link.confidence);
    paintServiceLink(link, ctx, globalScale, {
      color: EDGE_COLORS[link.type] || "#6b6f65",
      opacity: confStyle.opacity,
      dash: confStyle.dash,
      // An edge survives focus only if it actually touches the focused service.
      // Matching on neighbour membership alone would keep edges *between* two
      // neighbours, which are not this service's dependencies.
      dimmed: !!focus && !(focus.inbound.includes(link) || focus.outbound.includes(link)),
      selected: selectedEdge?.id === link.id,
      // Highlight is independent of node focus: focus narrows by adjacency,
      // highlight narrows by relationship kind. Both dim rather than remove.
      lit: highlightedEdgeTypes.length === 0 || highlightedEdgeTypes.includes(link.type),
    });
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
        onRenderFramePre={beginFrame}
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
        onEngineStop={onEngineStop}
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
      {/* Nothing is being arranged when nothing was drawable, and the progress
          message would clear into a blank canvas with no explanation. */}
      {!layoutReady && !emptyState && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#fbfaf6]/90
                        text-xs font-medium text-[#6e7168]">
          Arranging service map…
        </div>
      )}
      {emptyState && (
        <GraphCanvasMessage title={emptyState.title} detail={emptyState.detail} />
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
        <ServiceMapFocusPanel node={focusNode} incoming={focus.inbound}
          outgoing={focus.outbound} onClear={() => setFocusNode(null)} />
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
  const [minConf, setMinConf] = useState(0.6);
  const { serviceMapData, loading, loadError, setLoadError } =
    useServiceMapData(minConf);

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
