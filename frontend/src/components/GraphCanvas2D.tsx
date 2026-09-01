import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useGraphStore } from "@/store/graphStore";
import { useGraph2DLayout } from "@/hooks/useGraph2DLayout";
import { useGraphProjection } from "@/hooks/useGraphProjection";
import type { ForceGraph2DMethods } from "@/hooks/useGraphControls";
import type { GraphNode } from "@/lib/types";
import { graphGroupOf, getNodeColor } from "@/lib/graphStyle";
import { isModuleGroup, moduleGroupKey } from "@/lib/graphOverviewProjection";
import {
  buildLabelBudget,
  buildNodeIndex,
  computeFocusContext,
} from "@/lib/graph2dProjection";
import {
  paintLink,
  paintModuleRegions,
  paintNode,
  paintNodePointerArea,
} from "@/lib/graph2dPainter";
import { endpointId } from "@/lib/graphVisibility";
import { effectiveRepoIds } from "@/lib/graphNavigation";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import GraphContextBar from "@/components/GraphContextBar";
import { useGraphBackNavigation } from "@/hooks/useGraphBackNavigation";

export default function GraphCanvas2D() {
  const {
    selectedRepo,
    repos,
    scopeRepoIds,
    connectionsOnly,
    highlightedEdgeTypes,
    nodes,
    links,
    selectedNode,
    setSelectedNode,
    setSelectedEdge,
    showLabels,
    showParticles,
    viewMode,
    loadingGraph,
    error,
    filteredNodeTypes,
    filteredEdgeTypes,
    hideLockfileDeps,
    clientConfig,
  } = useGraphStore();
  const [containerEl, setContainerEl] = useState<HTMLDivElement | null>(null);
  const [ForceGraphComponent, setForceGraphComponent] = useState<any>(null);
  const [hoverNode, setHoverNode] = useState<GraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const graphRef = useRef<ForceGraph2DMethods | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const labelOccupancyRef = useRef<Array<{
    left: number; right: number; top: number; bottom: number;
  }>>([]);

  useEffect(() => {
    let mounted = true;
    import("react-force-graph-2d").then((module) => {
      if (mounted) setForceGraphComponent(() => module.default);
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
    const observer = new ResizeObserver(measure);
    observer.observe(containerEl);
    return () => observer.disconnect();
  }, [containerEl]);

  const repoIds = useMemo(
    () => effectiveRepoIds(repos, scopeRepoIds, selectedRepo),
    [repos, scopeRepoIds, selectedRepo],
  );
  const scopeKey = repoIds.join(",");
  const {
    baseNodes,
    visibleNodes,
    visibleLinks,
    projectionMode,
    expandedGroup,
    setExpandedGroup,
    projectedTotalNodeCount,
  } = useGraphProjection({
    nodes, links,
    hiddenNodeTypes: filteredNodeTypes,
    hiddenEdgeTypes: filteredEdgeTypes,
    hideLockfileDeps,
    connectionsOnly,
    selectedNodeId: selectedNode?.id ?? null,
    viewMode,
    scopeKey,
    detailNodeLimit: clientConfig?.graph_detail_node_limit ?? 80,
  });
  const visibleNodeIds = useMemo(
    () => new Set(baseNodes.map((node) => node.id)),
    [baseNodes],
  );
  const graphData = useMemo(
    () => ({ nodes: visibleNodes, links: visibleLinks }),
    [visibleLinks, visibleNodes],
  );
  const moduleOrder = useMemo(
    () => [...new Set(baseNodes.map(graphGroupOf))].sort(),
    [baseNodes],
  );
  const highlightedNodeIds = useMemo(() => {
    const ids = new Set<string>();
    if (!highlightedEdgeTypes.length) return ids;
    for (const link of visibleLinks) {
      if (!highlightedEdgeTypes.includes(link.type)) continue;
      ids.add(endpointId(link.source));
      ids.add(endpointId(link.target));
    }
    return ids;
  }, [highlightedEdgeTypes, visibleLinks]);
  const focusId = selectedNode?.id ?? hoverNode?.id ?? null;
  const focus = useMemo(
    () => computeFocusContext(visibleLinks, focusId),
    [focusId, visibleLinks],
  );
  const labelBudget = useMemo(
    () => buildLabelBudget(visibleNodes, visibleLinks, focusId),
    [focusId, visibleLinks, visibleNodes],
  );
  const nodeIndex = useMemo(() => buildNodeIndex(visibleNodes), [visibleNodes]);

  useEffect(() => {
    if (!selectedNode) return;
    const loaded = nodes.some((node) => node.id === selectedNode.id);
    if (loaded && !visibleNodeIds.has(selectedNode.id)) setSelectedNode(null);
  }, [nodes, selectedNode, setSelectedNode, visibleNodeIds]);

  const physicsEnabled = useGraph2DLayout({
    graphRef,
    nodes: visibleNodes,
    links: visibleLinks,
    dimensions,
    showLabels,
    engineReady: Boolean(ForceGraphComponent),
    scopeKey: `${scopeKey}:${projectionMode}:${expandedGroup ?? selectedNode?.id ?? ""}`,
    viewMode,
    selectedNodeId: selectedNode?.id ?? null,
  });
  const drawNode = useCallback((node: any, context: CanvasRenderingContext2D, scale: number) => {
    paintNode(node, context, scale, {
      selectedId: selectedNode?.id ?? null,
      hoveredId: hoverNode?.id ?? null,
      focus,
      highlightedNodeIds,
      labels: labelBudget,
      showLabels,
      moduleOrder,
      labelOccupancy: labelOccupancyRef.current,
    });
  }, [focus, highlightedNodeIds, hoverNode?.id, labelBudget, moduleOrder,
      selectedNode?.id, showLabels]);
  const drawLink = useCallback((link: any, context: CanvasRenderingContext2D, scale: number) => {
    paintLink(link, context, scale, {
      nodeIndex: nodeIndex as any,
      focus,
      highlightedTypes: highlightedEdgeTypes,
      showParticles,
    });
  }, [focus, highlightedEdgeTypes, nodeIndex, showParticles]);

  useEffect(() => () => {
    document.body.style.cursor = "default";
  }, []);
  useEffect(() => {
    visibleLinks.forEach((link: any, index) => {
      if (link.__phase == null) link.__phase = (index * 0.37) % 1;
    });
  }, [visibleLinks]);

  const navigateBack = useGraphBackNavigation();

  if (loadingGraph || !ForceGraphComponent) {
    return <GraphCanvasMessage title={loadingGraph ? "Loading graph data…" : "Loading 2D engine…"} />;
  }
  if (error && nodes.length === 0) {
    return <GraphCanvasMessage title="Graph unavailable" detail={error} warning />;
  }
  if (nodes.length === 0 || visibleNodes.length === 0) {
    return <GraphCanvasMessage
      title={nodes.length ? "Every node is filtered out" : "Nothing to draw"}
      detail={nodes.length ? "Re-enable a node type or lockfile leaves in the sidebar." : "The selected scope returned no drawable nodes."}
    />;
  }

  return (
    <div
      ref={setContainerEl}
      tabIndex={0}
      role="application"
      aria-label={`2D dependency graph, ${visibleNodes.length} displayed nodes and ${visibleLinks.length} displayed edges.`}
      className="absolute inset-0 outline-none"
      onKeyDown={(event) => {
        if (event.key !== "Escape") return;
        navigateBack();
      }}
      onPointerMove={(event) => {
        if (!tooltipRef.current) return;
        tooltipRef.current.style.left = `${event.nativeEvent.offsetX}px`;
        tooltipRef.current.style.top = `${event.nativeEvent.offsetY}px`;
      }}
      onPointerLeave={() => {
        setHoverNode(null);
        document.body.style.cursor = "default";
      }}
    >
      <GraphContextBar
        projectionMode={projectionMode}
        viewMode={viewMode}
        expandedGroup={expandedGroup}
        selectedNode={selectedNode}
        visibleNodeCount={visibleNodes.length}
        visibleEdgeCount={visibleLinks.length}
        loadedNodeCount={nodes.length}
        eligibleNodeCount={baseNodes.length}
        totalNodeCount={projectedTotalNodeCount}
        onBack={navigateBack}
      />
      <span className="sr-only" aria-live="polite">
        {selectedNode
          ? `Focused ${selectedNode.label}, ${focus.nodeIds.size - 1} neighbors`
          : expandedGroup
            ? `Module ${expandedGroup}, ${visibleNodes.length} displayed nodes`
            : `${viewMode} grouped overview`}
      </span>
      <ForceGraphComponent
        ref={graphRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        backgroundColor="#fbfaf6"
        onRenderFramePre={(context: CanvasRenderingContext2D, scale: number) => {
          labelOccupancyRef.current = [];
          paintModuleRegions(context, visibleNodes as any, scale, moduleOrder,
            labelOccupancyRef.current);
        }}
        nodeCanvasObject={drawNode}
        nodeCanvasObjectMode={() => "replace"}
        nodePointerAreaPaint={paintNodePointerArea}
        linkCanvasObject={drawLink}
        linkCanvasObjectMode={() => "replace"}
        d3VelocityDecay={physicsEnabled ? 0.3 : 1}
        d3AlphaDecay={physicsEnabled ? 0.025 : 1}
        warmupTicks={physicsEnabled ? 24 : 0}
        cooldownTicks={physicsEnabled ? 220 : 0}
        onNodeClick={(node: GraphNode) => {
          const groupKey = moduleGroupKey(node);
          if (isModuleGroup(node) && groupKey) setExpandedGroup(groupKey);
          else setSelectedNode(node);
        }}
        onLinkClick={(link: any) => { if (!link.aggregate) setSelectedEdge(link); }}
        onNodeHover={(node: GraphNode | null) => {
          setHoverNode(node);
          document.body.style.cursor = node ? "pointer" : "default";
        }}
        onBackgroundClick={() => {
          if (selectedNode || useGraphStore.getState().selectedEdge) navigateBack();
        }}
      />
      {hoverNode && !selectedNode && (
        <div ref={tooltipRef} className="absolute z-20 pointer-events-none -translate-x-1/2 -translate-y-[120%] rounded-md border border-[#d4cfc3] bg-[#fffefa]/95 px-3 py-2 text-xs text-[#252821] shadow-lg">
          <div className="flex items-center gap-2 font-semibold">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: getNodeColor(hoverNode.type) }} />
            <span>{hoverNode.label}</span>
          </div>
          <div className="mt-1 font-mono text-2xs text-[#6e7168]">{hoverNode.type}</div>
          {hoverNode.path && <div className="max-w-[260px] truncate font-mono text-2xs text-[#6e7168]">{hoverNode.path}</div>}
        </div>
      )}
    </div>
  );
}
