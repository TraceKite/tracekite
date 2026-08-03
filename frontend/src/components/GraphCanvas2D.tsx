import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useGraphStore } from "@/store/graphStore";
import { api, type ApiError } from "@/lib/api";
import { isPreviewMode } from "@/lib/previewFixtures";
import { AlertTriangle, RefreshCw, SearchX } from "lucide-react";
import {
  getNodeColor,
  getModuleColor,
  moduleOf,
  getNodeSize,
  getEdgeColor,
  getEdgeWidth,
  getConfidenceStyle,
} from "@/lib/graphStyle";
import { forceX, forceY } from "d3-force";
import type { GraphNode } from "@/lib/types";

// Only methods force-graph actually exposes. `refresh` used to be declared
// here, which is why calling it type-checked and then threw at runtime.
interface ForceGraph2DMethods {
  zoomToFit: (ms?: number, padding?: number) => void;
  centerAt: (x?: number, y?: number, ms?: number) => void;
  zoom: (k?: number, ms?: number) => void;
  pauseAnimation: () => void;
  resumeAnimation: () => void;
  d3Force(name: string): any;
  d3Force(name: string, force: any | null): ForceGraph2DMethods;
  d3ReheatSimulation: () => void;
}

const ALWAYS_LABEL_TYPES = new Set(["Repo", "Folder", "Package", "File"]);

const EMPTY_STATS = {
  total_nodes: 0, total_edges: 0, node_types: {}, edge_types: {},
  files: 0, apis: 0, dependencies: 0, external_systems: 0,
};

/** Say what actually failed. A blank canvas is not a diagnosis. */
function describeLoadError(err: ApiError): { title: string; detail: string } {
  if (err?.status === 401) {
    return {
      title: "Not authorized",
      detail: "The session token was rejected. Reconnect to load this repository.",
    };
  }
  if (err?.status === 404) {
    return { title: "Repository not found", detail: "It may have been deleted since this page loaded." };
  }
  if (err?.status === 500) {
    return { title: "The server failed to build the graph", detail: err.message };
  }
  if (err?.status === undefined) {
    return { title: "Cannot reach the backend", detail: "Check that the API is running." };
  }
  return { title: `Request failed (${err.status})`, detail: err.message };
}

export default function GraphCanvas2D() {
  const {
    selectedRepo,
    scopeRepoIds,
    connectionsOnly,
    setBridgeCount,
    highlightedEdgeTypes,
    focusNodeId,
    focusNodeRepo,
    nodes,
    links,
    setGraphData,
    setSelectedNode,
    selectedNode,
    setSelectedEdge,
    showLabels,
    showParticles,
    viewMode,
    loadingGraph,
    setLoadingGraph,
    setError,
    setGraphControlCallbacks,
    filteredNodeTypes,
    filteredEdgeTypes,
  } = useGraphStore();

  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const fgRef = useRef<ForceGraph2DMethods | null>(null);
  const [ForceGraphComponent, setForceGraphComponent] = useState<any>(null);
  const [physicsEnabled, setPhysicsEnabled] = useState(true);
  const [hoverNode, setHoverNode] = useState<GraphNode | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let mounted = true;
    import("react-force-graph-2d").then((mod) => {
      if (!mounted) return;
      setForceGraphComponent(() => mod.default);
    });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    if (!containerEl) return;
    const measure = () => {
      const rect = containerEl.getBoundingClientRect();
      setDimensions({ width: Math.round(rect.width), height: Math.round(rect.height) });
    };
    measure();
    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(measure);
      ro.observe(containerEl);
    } else {
      window.addEventListener("resize", measure);
    }
    return () => {
      if (ro) ro.disconnect();
      else window.removeEventListener("resize", measure);
    };
  }, [containerEl]);

  /** Repos this canvas draws. Scope wins when set, so the Repo tab obeys the
   *  same picker as Service Map and Trace; `selectedRepo` remains the fallback
   *  and still drives the stats panel and the refresh/delete actions. */
  const repoIds = useMemo(
    () => (scopeRepoIds.length > 0
      ? scopeRepoIds
      : selectedRepo ? [selectedRepo.id] : []),
    [scopeRepoIds, selectedRepo]);
  const repoKey = repoIds.join(",");

  useEffect(() => {
    if (repoIds.length === 0) return;
    // Fixture mode already seeded the store; a fetch here can only 401.
    if (isPreviewMode()) return;
    let cancelled = false;
    setLoadingGraph(true);
    setLoadError(null);
    // The endpoint caps at 500 nodes per repo. Drawing several repos at that
    // cap each would produce a canvas nobody can read, so the per-repo budget
    // shrinks as repos are added and the total stays in the same range a
    // single repo already produced.
    if (focusNodeId && focusNodeRepo) {
      api.getGraph(focusNodeRepo, {
        view: "impact", focus_node_id: focusNodeId, depth: 2, limit: 150,
      })
        .then((data) => {
          if (cancelled) return;
          // ADD the node and its neighbourhood to what is already drawn,
          // rather than replacing it. Swapping the canvas for a dozen nodes
          // trades the entire repository for one file — you find the node and
          // lose every bit of context that made it worth finding.
          //
          // Read the current graph off the store instead of closing over it,
          // so merging cannot retrigger this effect.
          const current = useGraphStore.getState();
          const byId = new Map<string, any>(
            (current.nodes as any[]).map((n) => [n.id, n]));
          for (const n of data.nodes ?? []) {
            const prev = byId.get(n.id) ?? {};
            byId.set(n.id, { ...prev, ...n,
                             repo_id: (n as any).repo_id ?? focusNodeRepo });
          }
          const seen = new Set(
            (current.links as any[]).map((l: any) =>
              `${typeof l.source === "object" ? l.source.id : l.source}->` +
              `${typeof l.target === "object" ? l.target.id : l.target}->${l.type}`));
          const merged = [...(current.links as any[])];
          for (const l of data.links ?? []) {
            const key = `${l.source}->${l.target}->${l.type}`;
            if (!seen.has(key)) { seen.add(key); merged.push(l); }
          }
          setGraphData([...byId.values()], merged, current.stats ?? data.stats);
        })
        .catch((err: any) => {
          if (cancelled) return;
          setError(err.message);
          setLoadError(err as ApiError);
        })
        .finally(() => { if (!cancelled) setLoadingGraph(false); });
      return () => { cancelled = true; };
    }

    const perRepo = Math.max(80, Math.floor(300 / repoIds.length));
    Promise.all([
      ...repoIds.map((id) =>
        api.getGraph(id, { view: viewMode, limit: perRepo })
          // One unreadable repo must not blank the whole canvas.
          .then((data) => ({ id, data }))
          .catch(() => null)),
      // The per-repo graphs are intra-repo by construction, so on their own
      // several of them are disconnected islands. The bridges — a call site
      // INVOKES a contract another repo's endpoint EXPOSES — are what makes
      // the selection one picture rather than N pictures.
      // Fetched for ANY selection, not just several repos: a monorepo's
      // boundaries are between its modules, and requiring two repos hid every
      // crossing inside one.
      api.getCodeBridges(repoIds).catch(() => ({ nodes: [], links: [] })),
    ])
      .then((results) => {
        if (cancelled) return;
        const bridges = results[results.length - 1] as { nodes: any[]; links: any[] };
        const ok = results.slice(0, -1)
          .filter(Boolean) as { id: string; data: any }[];
        if (ok.length === 0) throw new Error("No repository graph could be loaded");

        // Tag provenance at merge time: per-repo nodes carry no repo_id of
        // their own, and the details drawer needs to know which repo to ask.
        const byId = new Map<string, any>();
        for (const { id, data } of ok) {
          for (const n of data.nodes ?? []) {
            byId.set(n.id, { ...n, repo_id: n.repo_id ?? id });
          }
        }
        // Bridge endpoints may fall outside a repo's capped sample, so they
        // are merged in rather than assumed present — otherwise the very
        // edges that justify the multi-repo view would dangle.
        for (const n of bridges.nodes ?? []) {
          byId.set(n.id, { ...(byId.get(n.id) ?? {}), ...n });
        }
        const nodes = [...byId.values()];
        const links = [
          ...ok.flatMap(({ data }) => data.links ?? []),
          ...(bridges.links ?? []),
        ];
        setBridgeCount(bridges.links?.length ?? 0);
        const stats = ok.length === 1 ? ok[0].data.stats : {
          ...EMPTY_STATS,
          total_nodes: nodes.length,
          total_edges: links.length,
        };
        setGraphData(nodes, links, stats);
      })
      .catch((err: any) => {
        if (cancelled) return;
        // The store's `error` is written by nine call sites and read by none,
        // so relying on it alone means this tab fails to a blank canvas with
        // no explanation. Keep a local copy that the view actually renders.
        setError(err.message);
        setLoadError(err as ApiError);
        setGraphData([], [], EMPTY_STATS);
      })
      .finally(() => {
        if (!cancelled) setLoadingGraph(false);
      });
    return () => { cancelled = true; };
  }, [repoKey, viewMode, focusNodeId, focusNodeRepo, setGraphData,
      setLoadingGraph, setError, setBridgeCount, reloadKey]);


  /** Modules on the canvas, stable order — hues must not reshuffle on redraw. */
  const moduleOrder = useMemo(() => {
    const seen = new Set<string>();
    for (const n of nodes as any[]) {
      const key = n.module ?? moduleOf(n.path);
      if (key) seen.add(key);
    }
    return [...seen].sort();
  }, [nodes]);

  const visibleNodes = useMemo(() => {
    const typed = (nodes as any[]).filter((n) => !filteredNodeTypes.includes(n.type));
    if (!connectionsOnly) return typed;
    // Only the tissue that joins repos: every node touched by a cross-repo
    // edge. Filtering by node TYPE would not do -- a File is structure in one
    // place and a call site in another; what matters is whether it takes part
    // in a bridge.
    const touched = new Set<string>();
    for (const l of links as any[]) {
      if (l.type !== "INVOKES" && l.type !== "EXPOSES") continue;
      touched.add(typeof l.source === "object" ? l.source.id : l.source);
      touched.add(typeof l.target === "object" ? l.target.id : l.target);
    }
    return typed.filter((n) => touched.has(n.id));
  }, [nodes, links, filteredNodeTypes, connectionsOnly]);

  const visibleLinks = useMemo(() => {
    const nodeIdSet = new Set(visibleNodes.map((n) => n.id));
    return (links as any[]).filter((l) => {
      if (filteredEdgeTypes.includes(l.type)) return false;
      const sourceId = typeof l.source === "object" ? l.source?.id : l.source;
      const targetId = typeof l.target === "object" ? l.target?.id : l.target;
      return nodeIdSet.has(sourceId) && nodeIdSet.has(targetId);
    });
  }, [links, visibleNodes, filteredEdgeTypes]);

  /** Endpoints of every highlighted edge that is actually DRAWN.
   *
   * Computed from visibleLinks, not links: a node whose only highlighted edge
   * had been filtered away used to stay bright, claiming an emphasis the
   * canvas was not showing. */
  const highlightedNodeIds = useMemo(() => {
    const out = new Set<string>();
    if (highlightedEdgeTypes.length === 0) return out;
    for (const l of visibleLinks as any[]) {
      if (!highlightedEdgeTypes.includes(l.type)) continue;
      out.add(typeof l.source === "object" ? l.source.id : l.source);
      out.add(typeof l.target === "object" ? l.target.id : l.target);
    }
    return out;
  }, [visibleLinks, highlightedEdgeTypes]);

  const graphData = useMemo(() => ({ nodes: visibleNodes, links: visibleLinks }), [visibleNodes, visibleLinks]);

  // Drop a selection the user has filtered away — but ONLY if the node was
  // loaded in the first place. Search queries the whole repository while this
  // canvas holds a capped sample, so a hit outside the sample used to be
  // cleared the instant search selected it: the dropdown closed and nothing
  // else happened, which is precisely how it looked broken.
  useEffect(() => {
    if (!selectedNode) return;
    const loaded = (nodes as any[]).some((n) => n.id === selectedNode.id);
    const visible = visibleNodes.some((n) => n.id === selectedNode.id);
    if (loaded && !visible) setSelectedNode(null);
  }, [nodes, visibleNodes, selectedNode, setSelectedNode]);

  /** Bring a selected node into view. Selecting something off-screen and
   *  leaving the camera where it was reads as "nothing happened". */
  useEffect(() => {
    if (!selectedNode || !fgRef.current) return;
    const drawn = (visibleNodes as any[]).find((n) => n.id === selectedNode.id);
    if (drawn?.x == null || drawn?.y == null) return;
    fgRef.current.centerAt(drawn.x, drawn.y, 600);
    fgRef.current.zoom(2.2, 600);
  }, [selectedNode, visibleNodes]);

  const { neighborNodeIds, incidentLinkIds } = useMemo(() => {
    const focusId = selectedNode?.id || hoverNode?.id;
    if (!focusId) return { neighborNodeIds: new Set<string>(), incidentLinkIds: new Set<string>() };
    const neighborNodeIds = new Set<string>([focusId]);
    const incidentLinkIds = new Set<string>();
    visibleLinks.forEach((link) => {
      const sourceId = typeof link.source === "object" ? link.source.id : link.source;
      const targetId = typeof link.target === "object" ? link.target.id : link.target;
      const linkId = link.id || `${sourceId}->${targetId}`;
      if (sourceId === focusId || targetId === focusId) {
        neighborNodeIds.add(sourceId);
        neighborNodeIds.add(targetId);
        incidentLinkIds.add(linkId);
      }
    });
    return { neighborNodeIds, incidentLinkIds };
  }, [selectedNode?.id, hoverNode?.id, visibleLinks]);

  const drawGlowCircle = (ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, color: string, alpha: number) => {
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.shadowBlur = radius * 2.5;
    ctx.shadowColor = color;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  };

  const drawNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const type = node.type || "File";
      const color = getNodeColor(type);
      const baseSize = getNodeSize(type, Math.min(node.size || 5, 10));
      const radius = baseSize * 0.55;

      const isSelected = node.id === selectedNode?.id;
      const isHovered = node.id === hoverNode?.id;
      const isFocused = isSelected || isHovered;
      const isNeighbor = neighborNodeIds.size === 0 || neighborNodeIds.has(node.id);
      // A node earns its brightness by taking part in a highlighted edge.
      // Dimming every node would hide the endpoints the highlight is about.
      const onLit = highlightedNodeIds.size === 0 || highlightedNodeIds.has(node.id);
      const alpha = (isNeighbor ? 1 : 0.2) * (onLit ? 1 : 0.12);

      drawGlowCircle(ctx, node.x, node.y, radius, color, alpha * 0.9);

      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
      ctx.fill();

      // Which repository this node came from, as a ring. Drawn only when
      // several repos are on screen -- with one repo there is nothing to
      // tell apart and the ring would be noise. The fill keeps carrying the
      // node TYPE, so the two encodings never fight for the same channel.
      const repoRing = getModuleColor(node.module ?? moduleOf(node.path), moduleOrder);
      if (repoRing) {
        ctx.strokeStyle = repoRing;
        ctx.lineWidth = 1.6 / globalScale;
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 1.8 / globalScale, 0, Math.PI * 2);
        ctx.stroke();
      }

      ctx.fillStyle = "rgba(255,255,255,0.35)";
      ctx.beginPath();
      ctx.arc(node.x - radius * 0.35, node.y - radius * 0.35, radius * 0.25, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (isFocused) {
        ctx.save();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.9;
        ctx.shadowBlur = 8;
        ctx.shadowColor = "#ffffff";
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      const showLabel = showLabels && node.id !== hoverNode?.id && (type === "Repo" || (type === "Folder" && globalScale > 0.25) || (ALWAYS_LABEL_TYPES.has(type) && globalScale > 0.6) || globalScale > 1.6);
      if (showLabel) {
        const label = String(node.label || node.name || "").slice(0, 40);
        ctx.save();
        const pxScale = 1 / Math.max(globalScale, 0.1);
        const fontSize = Math.max(9, Math.min(12, radius * 0.5 + 5));
        ctx.font = `600 ${fontSize * pxScale}px ui-sans-serif, system-ui, sans-serif`;
        const textMetrics = ctx.measureText(label);
        const paddingX = 6 * pxScale;
        const paddingY = 3 * pxScale;
        const pillW = textMetrics.width + paddingX * 2;
        const pillH = (10 + 3 * 2) * pxScale;
        const nodeRadiusScreen = radius * globalScale;
        const offsetScreen = nodeRadiusScreen + (pillH * globalScale) / 2 + 4;
        const pillX = node.x - pillW / 2;
        const pillY = node.y - offsetScreen * pxScale;

        ctx.globalAlpha = alpha * 0.98;
        ctx.fillStyle = "rgba(0, 0, 0, 0.85)";
        ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
        ctx.lineWidth = 1 * pxScale;
        ctx.beginPath();
        ctx.roundRect(pillX, pillY, pillW, pillH, 8 * pxScale);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#f8fafc";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(label, node.x, pillY + pillH / 2);
        ctx.restore();
      }
    },
    [selectedNode?.id, hoverNode?.id, neighborNodeIds, showLabels, moduleOrder,
     highlightedNodeIds]
  );

  const nodePointerAreaPaint = useCallback((node: any, color: string, ctx: CanvasRenderingContext2D) => {
    const type = node.type || "File";
    const radius = getNodeSize(type, Math.min(node.size || 5, 10)) * 0.55 + 4;
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }, []);

  const drawLink = useCallback(
    (link: any, ctx: CanvasRenderingContext2D) => {
      const start = link.source && typeof link.source === "object" ? link.source : visibleNodes.find((n) => n.id === link.source);
      const end = link.target && typeof link.target === "object" ? link.target : visibleNodes.find((n) => n.id === link.target);
      if (!start || !end || start.x == null || end.x == null) return;

      const type = link.type || "RELATED_TO";
      const color = getEdgeColor(type);
      // A highlighted edge also thickens: colour alone loses at low zoom,
      // which is exactly when you are scanning for where these edges are.
      const emphasised = highlightedEdgeTypes.includes(type);
      const width = getEdgeWidth(type) * (emphasised ? 2.2 : 1);
      const isImportant = width >= 1.2;
      const sourceId = start.id;
      const targetId = end.id;
      const linkId = link.id || `${sourceId}->${targetId}`;
      const isIncident = incidentLinkIds.size === 0 || incidentLinkIds.has(linkId);
      // Highlight is a SECOND, independent dimension of emphasis: hovering a
      // node narrows by adjacency, highlighting narrows by relationship kind.
      // Both dim rather than remove, so an edge that fails either test still
      // draws the structure that gives the survivors their meaning.
      const lit = highlightedEdgeTypes.length === 0 || highlightedEdgeTypes.includes(type);
      const alpha = (isIncident ? 1 : 0.12) * (lit ? 1 : 0.07);

      const dx = end.x - start.x;
      const dy = end.y - start.y;
      const len = Math.hypot(dx, dy) || 1;
      const sourceRadius = getNodeSize(start.type, Math.min(start.size || 5, 10)) * 0.55;
      const targetRadius = getNodeSize(end.type, Math.min(end.size || 5, 10)) * 0.55;
      const gap = 2;
      const sx = start.x + (dx / len) * Math.min(len * 0.45, sourceRadius + gap);
      const sy = start.y + (dy / len) * Math.min(len * 0.45, sourceRadius + gap);
      const ex = end.x - (dx / len) * Math.min(len * 0.45, targetRadius + gap);
      const ey = end.y - (dy / len) * Math.min(len * 0.45, targetRadius + gap);

      const confStyle = getConfidenceStyle(link.confidence);

      ctx.save();
      ctx.globalAlpha = alpha * confStyle.opacity;

      ctx.strokeStyle = color;
      ctx.lineWidth = width * 0.9;
      ctx.lineCap = "round";
      const needsGlow = emphasised || (hoverNode && isIncident);
      if (needsGlow) {
        ctx.shadowBlur = 6;
        ctx.shadowColor = color;
        ctx.lineWidth = width * 1.8;
      } else {
        ctx.shadowBlur = 0;
      }
      ctx.setLineDash(confStyle.dash);
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.setLineDash([]);

      const angle = Math.atan2(dy, dx);
      const arrLen = 6 + width * 1.2;
      ctx.fillStyle = color;
      ctx.globalAlpha = alpha * confStyle.opacity;
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - arrLen * Math.cos(angle - Math.PI / 6), ey - arrLen * Math.sin(angle - Math.PI / 6));
      ctx.lineTo(ex - arrLen * Math.cos(angle + Math.PI / 6), ey - arrLen * Math.sin(angle + Math.PI / 6));
      ctx.closePath();
      ctx.fill();

      if (showParticles && isImportant && isIncident) {
        const t = ((Date.now() * 0.0015 + (link.__phase || 0)) % 1);
        const px = sx + (ex - sx) * t;
        const py = sy + (ey - sy) * t;
        ctx.fillStyle = "#ffffff";
        ctx.shadowBlur = 6;
        ctx.shadowColor = color;
        ctx.globalAlpha = alpha * confStyle.opacity;
        ctx.beginPath();
        ctx.arc(px, py, width * 0.7 + 1.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      ctx.restore();
    },
    [showParticles, incidentLinkIds, visibleNodes, highlightedEdgeTypes]
  );

  // How many children each node has. A containment graph is hub-and-spoke, and
  // the ring a hub's children settle on has circumference 2*pi*distance — so a
  // fixed distance is only ever right for one fan-out.
  const childCount = useMemo(() => {
    const counts = new Map<string, number>();
    visibleLinks.forEach((l: any) => {
      const s = typeof l.source === "object" ? l.source?.id : l.source;
      counts.set(s, (counts.get(s) ?? 0) + 1);
    });
    return counts;
  }, [visibleLinks]);

  const linkDistance = useCallback((link: any) => {
    const base = (() => {
      switch (link.type) {
        case "CONTAINS": return 28;
        case "IMPORTS": case "CALLS": return 75;
        case "EXTENDS": case "IMPLEMENTS": return 60;
        case "EXPOSES_API": return 90;
        default: return 50;
      }
    })();
    // A flat 28 pinned all 47 of a folder's files onto a radius-28 ring: the
    // cluster collapsed to a dot, its labels piled into an unreadable blob,
    // and charge then flung those dots far apart — dense specks in a mostly
    // empty canvas (measured: content filled 85% of the viewport but only
    // 10% of that had any ink). Size the ring to hold its children instead:
    // circumference >= children * spacing.
    const sourceId = typeof link.source === "object" ? link.source?.id : link.source;
    const kids = childCount.get(sourceId) ?? 1;
    if (kids <= 3) return base;
    const spacing = 17; // roughly a label's height plus breathing room
    return Math.min(Math.max(base, (kids * spacing) / (2 * Math.PI)), 260);
  }, [childCount]);

  const handleNodeClick = useCallback((node: any) => {
    if (node) {
      setSelectedNode(node as GraphNode);
      setSelectedEdge(null);
    }
  }, [setSelectedNode, setSelectedEdge]);

  const handleLinkClick = useCallback((link: any) => {
    setSelectedEdge(link);
    setSelectedNode(null);
  }, [setSelectedEdge, setSelectedNode]);

  const handleNodeHover = useCallback((node: any) => {
    setHoverNode((node as GraphNode) || null);
    if (typeof document !== "undefined") document.body.style.cursor = node ? "pointer" : "default";
  }, []);

  const handleResetCamera = useCallback(() => {
    fgRef.current?.centerAt(0, 0, 800);
    fgRef.current?.zoom(1, 800);
  }, []);

  // zoomToFit measures NODE COORDINATES, but every node draws a label beside
  // it, so the visual bounds are wider than what it fits. At 40px padding the
  // outermost labels were clipped to 0-1px margins. Pad for the label extent.
  const handleFitGraph = useCallback(() => fgRef.current?.zoomToFit(800, 90), []);

  // Forces MUST be applied through the ref. Passing `d3Force` as a prop looks
  // right and does nothing: react-kapsule omits method-named props, so every
  // graph in this app has been running d3 defaults (charge -30, link distance
  // 30) — which is why dense graphs collapsed into an unreadable ball.
  // The ref is null on the first run because the graph is imported lazily, and
  // bailing here left the defaults in place — the same race that stopped
  // zoomToFit from ever firing. Retry until the instance exists.
  useEffect(() => {
    let cancelled = false;
    let tries = 0;
    const apply = () => {
      if (cancelled) return;
      const graph = fgRef.current;
      if (!graph?.d3Force) {
        if (tries++ < 25) setTimeout(apply, 80);
        return;
      }
      // Charge is pairwise, so its total effect grows with n^2 while the
      // useful separation does not. At -250 across 300 nodes it dominated the
      // link force, blowing the clusters apart faster than the (now
      // fan-out-aware) rings could fill the space between them.
      graph.d3Force("charge")?.strength(-120)?.distanceMax(600);
      graph.d3Force("link")?.distance(linkDistance)?.strength(0.6);
      // A pure charge/link equilibrium is radially symmetric, so the graph
      // settles into a circle. zoomToFit then scales to the limiting axis —
      // height, on any landscape viewport — and the sides go empty (measured:
      // 263px and 208px of dead margin against 54px top and bottom). Pull
      // harder along y than x so the equilibrium is an ellipse matching the
      // canvas aspect, and the fit is limited by both axes at once.
      // Extent along an axis falls roughly as 1/sqrt(strength), so to reach a
      // width:height ratio of `aspect` the strengths must differ by aspect^2.
      // A 1.23x differential at strength 0.02 was far too weak against charge
      // and link — it left the drawing taller than wide (0.89) on a 1.23
      // canvas. Anchor the pair around a stronger centre and split by aspect.
      const aspect = Math.max(dimensions.width / Math.max(dimensions.height, 1), 0.2);
      const k = 0.05;
      graph.d3Force("x", forceX(0).strength(k / aspect));
      graph.d3Force("y", forceY(0).strength(k * aspect));
      // Collision was sized to the node dot alone, so 47 labels could stack in
      // the same few pixels. Reserve the label's footprint too when labels are
      // actually being drawn.
      graph.d3Force("collide")
        ?.radius((n: any) => {
          const r = getNodeSize(n.type, Math.min(n.size || 5, 10)) * 0.55 + 2;
          return showLabels ? r + 9 : r;
        })
        ?.iterations(2);
      graph.d3ReheatSimulation?.();
    };
    apply();
    return () => { cancelled = true; };
  }, [linkDistance, graphData, showLabels, ForceGraphComponent, dimensions.width, dimensions.height]);

  const handleTogglePhysics = useCallback(() => {
    setPhysicsEnabled((prev) => {
      const next = !prev;
      // `refresh()` does not exist on force-graph — it was invented in a
      // hand-written interface, so this threw a TypeError inside a setState
      // updater and the ErrorBoundary replaced the whole app.
      if (next) fgRef.current?.resumeAnimation();
      else fgRef.current?.pauseAnimation();
      return next;
    });
  }, []);

  const handleRotateGraph = useCallback(() => {
    visibleNodes.forEach((n: any) => {
      if (n.x != null && n.y != null) {
        const oldX = n.x;
        n.x = -n.y;
        n.y = oldX;
        n.vx = 0;
        n.vy = 0;
      }
    });
    fgRef.current?.d3ReheatSimulation();
  }, [visibleNodes]);

  useEffect(() => {
    setGraphControlCallbacks({ resetCamera: handleResetCamera, fitGraph: handleFitGraph, togglePhysics: handleTogglePhysics, rotateGraph: handleRotateGraph, physicsEnabled });
  }, [handleResetCamera, handleFitGraph, handleTogglePhysics, handleRotateGraph, physicsEnabled, setGraphControlCallbacks]);

  // The graph component is dynamically imported, so fgRef is still null the
  // first time this runs. The old version bailed on that and — with only
  // [visibleNodes.length, viewMode] as deps — never came back, so zoomToFit
  // never fired at all and the graph rendered at whatever zoom it happened to
  // start at, overflowing the viewport. Retry until the instance exists.
  useEffect(() => {
    if (!visibleNodes.length) return;
    let cancelled = false;
    let tries = 0;
    const attempt = () => {
      if (cancelled) return;
      if (!fgRef.current) {
        if (tries++ < 25) setTimeout(attempt, 80);
        return;
      }
      setTimeout(() => !cancelled && fgRef.current?.zoomToFit(800, 90), 1500);
    };
    attempt();
    return () => { cancelled = true; };
  }, [visibleNodes.length, viewMode, ForceGraphComponent]);

  const filterChangedRef = useRef(false);
  useEffect(() => {
    if (!visibleNodes.length || !fgRef.current) return;
    if (!filterChangedRef.current) { filterChangedRef.current = true; return; }
    const t = setTimeout(() => fgRef.current?.zoomToFit(800, 40), 1200);
    return () => clearTimeout(t);
  }, [filteredNodeTypes, filteredEdgeTypes, visibleNodes.length]);

  useEffect(() => {
    if (!selectedNode || !fgRef.current) return;
    const graphNode = visibleNodes.find((n) => n.id === selectedNode.id) || selectedNode;
    const sx = graphNode.x ?? 0;
    const sy = graphNode.y ?? 0;
    if (!sx && !sy) return;
    // Pan to the node, but do NOT force a zoom level. Slamming zoom to 1.8 on
    // every selection threw away whatever framing the user had set, so any
    // click re-zoomed the whole graph.
    fgRef.current.centerAt(sx, sy, 800);
  }, [selectedNode?.id, visibleNodes]);

  useEffect(() => {
    return () => { if (typeof document !== "undefined") document.body.style.cursor = "default"; };
  }, []);

  useEffect(() => {
    visibleLinks.forEach((link: any, idx: number) => {
      if (link.__phase == null) link.__phase = (idx * 0.37) % 1;
    });
  }, [visibleLinks]);

  if (loadingGraph || !ForceGraphComponent) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin mx-auto" />
          <p className="text-sm text-[#8c949e]">
            {loadingGraph ? "Loading graph data..." : "Loading 2D engine..."}
          </p>
        </div>
      </div>
    );
  }

  // Previously this fell straight through to the canvas, so a failed fetch and
  // an empty result both rendered as an unexplained black rectangle.
  if (loadError) {
    const { title, detail } = describeLoadError(loadError);
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="max-w-md text-center space-y-4">
          <div className="w-12 h-12 rounded-lg bg-amber-500/10 border border-amber-500/25
                          flex items-center justify-center mx-auto">
            <AlertTriangle className="w-6 h-6 text-amber-400" />
          </div>
          <div className="space-y-2">
            <h3 className="text-lg font-semibold text-[#e9ecef]">{title}</h3>
            <p className="text-sm text-[#aab2bb] leading-relaxed">{detail}</p>
          </div>
          <button
            onClick={() => {
              if (loadError.status === 401) window.dispatchEvent(new Event("auth-required"));
              setLoadError(null);
              setReloadKey((k) => k + 1);
            }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium
                       bg-white/5 hover:bg-white/10 border border-white/10 text-[#e9ecef] transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            {loadError.status === 401 ? "Reconnect" : "Retry"}
          </button>
        </div>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="max-w-md text-center space-y-3">
          <div className="w-12 h-12 rounded-lg bg-white/5 border border-white/10
                          flex items-center justify-center mx-auto">
            <SearchX className="w-6 h-6 text-[#8c949e]" />
          </div>
          <h3 className="text-lg font-semibold text-[#e9ecef]">Nothing to draw</h3>
          <p className="text-sm text-[#aab2bb] leading-relaxed">
            <span className="text-[#e9ecef]">{selectedRepo?.name}</span> returned no nodes for the{" "}
            <span className="font-mono text-[#e9ecef]">{viewMode}</span> view. It may still be
            ingesting, or this view's node types may not exist in it.
          </p>
        </div>
      </div>
    );
  }

  if (visibleNodes.length === 0) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6">
        <div className="max-w-md text-center space-y-3">
          <div className="w-12 h-12 rounded-lg bg-white/5 border border-white/10
                          flex items-center justify-center mx-auto">
            <SearchX className="w-6 h-6 text-[#8c949e]" />
          </div>
          <h3 className="text-lg font-semibold text-[#e9ecef]">Every node is filtered out</h3>
          <p className="text-sm text-[#aab2bb] leading-relaxed">
            The graph has {nodes.length} nodes, but the active node-type filters hide all of them.
            Re-enable a type in the sidebar.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={setContainerEl}
      className="absolute inset-0"
      onPointerMove={(e) => {
        if (tooltipRef.current) {
          tooltipRef.current.style.left = `${e.nativeEvent.offsetX}px`;
          tooltipRef.current.style.top = `${e.nativeEvent.offsetY}px`;
        }
      }}
      onPointerLeave={() => {
        setHoverNode(null);
        if (typeof document !== "undefined") document.body.style.cursor = "default";
      }}
    >
      <ForceGraphComponent
        ref={fgRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="rgba(0,0,0,0)"
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={() => "replace"}
        nodePointerAreaPaint={nodePointerAreaPaint}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={() => "replace"}
        d3VelocityDecay={physicsEnabled ? 0.3 : 1}
        d3AlphaDecay={physicsEnabled ? 0.02 : 0}
        warmupTicks={physicsEnabled ? 50 : 0}
        // `undefined` fell back to the 15s default cooldownTime. d3-force
        // converges in ~300 ticks; bounding it stops the main thread churning
        // long after the layout has visibly settled.
        cooldownTicks={physicsEnabled ? 400 : 0}
        // Frame the graph the moment the layout actually settles, rather than
        // trusting a fixed 1500ms timer to land after convergence.
        onEngineStop={() => fgRef.current?.zoomToFit(600, 90)}
        onNodeClick={handleNodeClick}
        onLinkClick={handleLinkClick}
        onNodeHover={handleNodeHover}
        onNodeDragEnd={(node: any) => { node.fx = node.x; node.fy = node.y; }}
      />
      {hoverNode && !selectedNode && (
        <div ref={tooltipRef} className="absolute pointer-events-none z-20" style={{ left: 0, top: 0, transform: "translate(-50%, -120%)" }}>
          <div className="rounded-lg px-3 py-2 text-xs space-y-1" style={{ background: "rgba(0,0,0,0.85)", border: "1px solid rgba(255,255,255,0.15)", backdropFilter: "blur(8px)" }}>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: getNodeColor(hoverNode.type) }} />
              <span className="font-medium text-[#e9ecef]">{hoverNode.label}</span>
            </div>
            <span className="text-2xs text-[#8c949e] bg-[#2b313a] px-1.5 py-0.5 rounded">{hoverNode.type}</span>
            {hoverNode.path && <p className="text-2xs text-[#8c949e] font-mono truncate max-w-[200px]">{hoverNode.path}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
