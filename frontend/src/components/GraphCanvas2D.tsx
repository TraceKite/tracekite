import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useGraphStore } from "@/store/graphStore";
import { useGraph2DLayout } from "@/hooks/useGraph2DLayout";
import { useGraph2DCameraFrame } from "@/hooks/useGraph2DCameraFrame";
import { useGraphProjection } from "@/hooks/useGraphProjection";
import type { ForceGraph2DMethods } from "@/hooks/useGraphControls";
import type { GraphNode } from "@/lib/types";
import { graphGroupOf } from "@/lib/graphStyle";
import { useGraphNodeClick } from "@/hooks/useGraphNodeClick";
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
import { cameraSceneKey, effectiveRepoIds } from "@/lib/graphNavigation";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import GraphContextBar from "@/components/GraphContextBar";
import Graph2DHoverCard from "@/components/Graph2DHoverCard";
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
    focusNodeId,
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
    baseLinks,
    visibleNodes,
    visibleLinks,
    projectionMode,
    expandedGroup,
    setExpandedGroup,
    openedNodeId,
    setExpandedNode,
    projectedTotalNodeCount,
  } = useGraphProjection({
    nodes, links,
    hiddenNodeTypes: filteredNodeTypes,
    hiddenEdgeTypes: filteredEdgeTypes,
    hideLockfileDeps,
    connectionsOnly,
    focusNodeId,
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
  const nodeIndex = useMemo(() => buildNodeIndex(visibleNodes), [visibleNodes]);
  // A module is never drawn among its own members. Focusing on one would dim
  // every node on the canvas and match none of them.
  const focusId = (selectedNode && nodeIndex.has(selectedNode.id)
    ? selectedNode.id : null) ?? hoverNode?.id ?? null;
  const focus = useMemo(
    () => computeFocusContext(visibleLinks, focusId),
    [focusId, visibleLinks],
  );
  const labelBudget = useMemo(
    () => buildLabelBudget(visibleNodes, visibleLinks, focusId),
    [focusId, visibleLinks, visibleNodes],
  );

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
  });
  const camera = useGraph2DCameraFrame({
    graphRef,
    nodes: visibleNodes,
    dimensions,
    ready: Boolean(ForceGraphComponent),
    sceneKey: cameraSceneKey({ repoIds, viewMode, focusNodeId, expandedGroup }),
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

  const openedLabel = visibleNodes.find((node) => node.id === openedNodeId)?.label ?? null;
  const { handleNodeClick, openNode } = useGraphNodeClick({
    onSelect: setSelectedNode,
    onOpenNode: setExpandedNode,
    onOpenGroup: setExpandedGroup,
  });
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
      onWheelCapture={camera.onUserZoom}
      onKeyDown={(event) => {
        if (event.key.toLowerCase() === "o" && selectedNode) openNode(selectedNode);
        else if (event.key === "Escape") navigateBack();
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
        openedLabel={openedLabel}
        hasSelection={Boolean(selectedNode)}
        visibleNodeCount={visibleNodes.length}
        visibleEdgeCount={visibleLinks.length}
        loadedNodeCount={nodes.length}
        loadedEdgeCount={links.length}
        eligibleNodeCount={baseNodes.length}
        totalNodeCount={projectedTotalNodeCount}
        onBack={navigateBack}
      />
      <span className="sr-only" aria-live="polite">
        {openedLabel
          ? `Opened ${openedLabel}, ${visibleNodes.length} displayed nodes`
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
        onEngineStop={camera.onEngineStop}
        d3VelocityDecay={physicsEnabled ? 0.3 : 1}
        d3AlphaDecay={physicsEnabled ? 0.025 : 1}
        warmupTicks={physicsEnabled ? 24 : 0}
        cooldownTicks={physicsEnabled ? 220 : 0}
        onNodeClick={handleNodeClick}
        onLinkClick={(link: any) => { if (!link.aggregate) setSelectedEdge(link); }}
        onNodeHover={(node: GraphNode | null) => {
          setHoverNode(node);
          document.body.style.cursor = node ? "pointer" : "default";
        }}
        onBackgroundClick={() => {
          if (selectedNode || useGraphStore.getState().selectedEdge) navigateBack();
        }}
      />
      {!selectedNode && <Graph2DHoverCard node={hoverNode} cardRef={tooltipRef} />}
    </div>
  );
}
