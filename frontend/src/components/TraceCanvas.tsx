import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EDGE_COLORS, getConfidenceStyle } from "@/lib/graphStyle";
import { useGraphStore } from "@/store/graphStore";

export default function TraceCanvas() {
  const { traceData, setSelectedEdge, selectedEdge } = useGraphStore();
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
