import { useEffect, useRef, useMemo, useCallback } from "react";
import { useGraphStore } from "@/store/graphStore";
import {
  initPhysicsNodes,
  computeLayoutAnchors,
  type Node3DPhysicsState,
  type LayoutAnchors,
  type Layout3DMode,
} from "@/lib/graph3dPhysics";
import {
  initNodeBuffers,
  initEdgeBuffers,
} from "@/lib/graph3dBufferBuilder";
import { isModuleGroup, moduleGroupKey } from "@/lib/graphOverviewProjection";
import { useGraph3DInteraction } from "@/hooks/useGraph3DInteraction";
import { useGraph3DShortcuts } from "@/hooks/useGraph3DShortcuts";
import { useGraph3DSceneLifecycle } from "@/hooks/useGraph3DSceneLifecycle";
import { useGraphProjection } from "@/hooks/useGraphProjection";
import { useGraph3DCameraFrame } from "@/hooks/useGraph3DCameraFrame";
import { useGraph3DRenderer } from "@/hooks/useGraph3DRenderer";
import Graph3DHud from "@/components/Graph3DHud";
import Graph3DTools from "@/components/Graph3DTools";
import GraphContextBar from "@/components/GraphContextBar";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";
import { effectiveRepoIds } from "@/lib/graphNavigation";
import { useGraphBackNavigation } from "@/hooks/useGraphBackNavigation";
export default function GraphCanvas3D() {
  const {
    nodes,
    links,
    repos,
    selectedRepo,
    scopeRepoIds,
    viewMode,
    selectedNode,
    setSelectedNode,
    layout3d,
    flow3d,
    showLabels,
    toggleShowLabels,
    autoOrbit3d,
    activePath3d,
    setActivePath3d,
    setHudMode3d,
    filteredNodeTypes,
    filteredEdgeTypes,
    searchQuery,
    hideLockfileDeps,
    connectionsOnly,
    highlightedEdgeTypes,
    loadingGraph,
    error,
    clientConfig,
  } = useGraphStore();
  const containerRef = useRef<HTMLDivElement>(null);
  const physicsNodesRef = useRef<Node3DPhysicsState[]>([]);
  const anchorsRef = useRef<LayoutAnchors>({ atlas: [], sphere: [], layers: [] });
  const alphaRef = useRef<number>(1.0);
  const hoverNodeRef = useRef<string | null>(null);
  const repoIds = useMemo(
    () => effectiveRepoIds(repos, scopeRepoIds, selectedRepo),
    [repos, scopeRepoIds, selectedRepo]);
  const scopeKey = repoIds.join(",");
  const {
    baseNodes, visibleNodes: sceneNodes, visibleLinks: sceneLinks,
    projectionMode, expandedGroup, setExpandedGroup, projectedTotalNodeCount,
  } = useGraphProjection({
    nodes, links, hiddenNodeTypes: filteredNodeTypes,
    hiddenEdgeTypes: filteredEdgeTypes, hideLockfileDeps, connectionsOnly,
    selectedNodeId: selectedNode?.id ?? null, viewMode, scopeKey,
    detailNodeLimit: clientConfig?.graph_detail_node_limit ?? 80,
  });
  const graphBlocked = loadingGraph || (Boolean(error) && nodes.length === 0) ||
    nodes.length === 0 || sceneNodes.length === 0;
  const layoutRef = useRef<Layout3DMode>(layout3d);
  const flowRef = useRef<boolean>(flow3d);
  const labelsRef = useRef<boolean>(showLabels);
  const orbitRef = useRef<boolean>(autoOrbit3d);
  const selectedRef = useRef<string | null>(selectedNode?.id || null);
  const pathRef = useRef<string[] | null>(activePath3d);
  const searchRef = useRef<string>(searchQuery);
  const highlightsRef = useRef<string[]>(highlightedEdgeTypes);
  layoutRef.current = layout3d;
  flowRef.current = flow3d;
  labelsRef.current = showLabels && !graphBlocked;
  orbitRef.current = autoOrbit3d;
  selectedRef.current = graphBlocked ? null : selectedNode?.id || null;
  pathRef.current = graphBlocked ? null : activePath3d;
  searchRef.current = searchQuery;
  highlightsRef.current = highlightedEdgeTypes;
  const nodeIndexMap = useMemo(
    () => new Map(sceneNodes.map((node, index) => [node.id, index])),
    [sceneNodes]);
  const linksRef = useRef(sceneLinks);
  linksRef.current = sceneLinks;
  const nodeIndexMapRef = useRef(nodeIndexMap);
  nodeIndexMapRef.current = nodeIndexMap;

  useEffect(() => {
    if (!selectedNode) return;
    const visible = baseNodes.some((node) => node.id === selectedNode.id);
    if (!visible) setSelectedNode(null);
  }, [baseNodes, selectedNode, setSelectedNode]);

  useEffect(() => {
    const anchors = computeLayoutAnchors(sceneNodes, sceneLinks);
    const activeAnchors = anchors[layout3d] || anchors.atlas;
    physicsNodesRef.current = initPhysicsNodes(sceneNodes, activeAnchors, sceneLinks);
    anchorsRef.current = anchors;
    alphaRef.current = 1.0;
  }, [sceneNodes, sceneLinks, layout3d]);

  useEffect(() => {
    alphaRef.current = 1.0;
  }, [layout3d, filteredNodeTypes, filteredEdgeTypes, hideLockfileDeps]);

  const activateAggregate = useCallback((node: typeof sceneNodes[number]) => {
    const groupKey = moduleGroupKey(node);
    if (!isModuleGroup(node) || !groupKey) return false;
    setExpandedGroup(groupKey);
    setHudMode3d("FOCUS");
    return true;
  }, [setExpandedGroup, setHudMode3d]);

  const {
    camRef,
    zoomLevel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerLeave,
    onWheel,
    onZoom,
    onResetZoom,
    onResetView,
    onClearFocus,
    onClick,
    activateNode,
  } = useGraph3DInteraction(
    sceneNodes,
    sceneLinks,
    selectedNode,
    setSelectedNode,
    setActivePath3d,
    setHudMode3d,
    activateAggregate,
  );
  useGraph3DCameraFrame(camRef, physicsNodesRef,
    `${projectionMode}:${expandedGroup ?? selectedNode?.id ?? ""}:${sceneNodes.length}`);
  const onSelectNodeId = useCallback((nodeId: string, pathMode = false) => {
    const pn = physicsNodesRef.current.find((n) => n.id === nodeId);
    if (pn) activateNode(pn, pathMode);
  }, [activateNode]);

  const { threeRef, labelPoolRef, clusterPoolRef, tooltipRef } = useGraph3DSceneLifecycle({
    containerRef,
    camRef,
    onSelectNode: onSelectNodeId,
  });

  const navigateBack = useGraphBackNavigation({
    onClearNode: onClearFocus,
    onClearGroup: () => setHudMode3d("OVERVIEW"),
  });
  useGraph3DShortcuts({ toggleShowLabels, onBack: navigateBack, containerRef });

  useGraph3DRenderer({
    containerRef, threeRef, labelPoolRef, clusterPoolRef, tooltipRef, camRef,
    physicsNodesRef, anchorsRef, alphaRef, hoverNodeRef, layoutRef, flowRef,
    labelsRef, orbitRef, selectedRef, pathRef, searchRef, highlightsRef,
    linksRef, nodeIndexMapRef, projectionMode,
  });

  useEffect(() => {
    const s = threeRef.current;
    if (!s || sceneNodes.length === 0) return;
    initNodeBuffers(s.nodeGeo, sceneNodes.length);
    initEdgeBuffers(s.edgeGeo, sceneLinks.length);
  }, [sceneNodes.length, sceneLinks.length]);

  // The WebGL scene is imperative and bound to this container. Overlay state
  // messages instead of unmounting it during every View Mode request.
  const graphMessage = loadingGraph
    ? <GraphCanvasMessage title="Loading graph data…" />
    : error && nodes.length === 0
      ? <GraphCanvasMessage title="Graph unavailable" detail={error} warning />
      : nodes.length === 0 || sceneNodes.length === 0
        ? <GraphCanvasMessage
      title={nodes.length ? "Every node is filtered out" : "Nothing to draw"}
      detail={nodes.length ? "Re-enable a node type or lockfile leaves in the sidebar." : "The selected scope returned no drawable nodes."}
          />
        : null;

  return (
    <div
      ref={containerRef}
      onPointerDown={onPointerDown}
      onPointerMove={(e) => onPointerMove(e, containerRef.current)}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerLeave}
      onClick={(e) => onClick(e, physicsNodesRef.current)}
      onWheel={onWheel}
      tabIndex={0}
      role="application"
      aria-busy={loadingGraph}
      aria-label={`3D dependency graph, ${sceneNodes.length} displayed nodes and ${sceneLinks.length} displayed edges. Drag to orbit and use Escape to go back one level.`}
      className="w-full h-full relative select-none cursor-grab active:cursor-grabbing overflow-hidden"
    >
      {graphMessage ?? <>
      <span className="sr-only" aria-live="polite">
        {selectedNode
          ? `Focused ${selectedNode.label}, ${selectedNode.type}`
          : expandedGroup
            ? `Module ${expandedGroup}, ${sceneNodes.length} displayed nodes`
            : `3D ${viewMode} grouped overview`}
      </span>
      <GraphContextBar
        projectionMode={projectionMode}
        viewMode={viewMode}
        expandedGroup={expandedGroup}
        selectedNode={selectedNode}
        visibleNodeCount={sceneNodes.length}
        visibleEdgeCount={sceneLinks.length}
        loadedNodeCount={nodes.length}
        eligibleNodeCount={baseNodes.length}
        totalNodeCount={projectedTotalNodeCount}
        activePath={Boolean(activePath3d?.length)}
        onBack={navigateBack}
      />
      <Graph3DHud onClearPath={() => setActivePath3d(null)} />
      <Graph3DTools
        onZoom={onZoom}
        onResetZoom={onResetZoom}
        onResetView={onResetView}
        zoomLevel={zoomLevel}
      />
      </>}
    </div>
  );
}
