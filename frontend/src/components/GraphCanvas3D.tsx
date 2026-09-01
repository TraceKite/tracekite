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
import { openTarget } from "@/lib/graphNodeGesture";
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
import { cameraSceneKey, effectiveRepoIds } from "@/lib/graphNavigation";
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
    focusNodeId,
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
    openedNodeId, setExpandedNode,
  } = useGraphProjection({
    nodes, links, hiddenNodeTypes: filteredNodeTypes,
    hiddenEdgeTypes: filteredEdgeTypes, hideLockfileDeps, connectionsOnly,
    focusNodeId, viewMode, scopeKey,
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
  pathRef.current = graphBlocked ? null : activePath3d;
  searchRef.current = searchQuery;
  highlightsRef.current = highlightedEdgeTypes;
  const nodeIndexMap = useMemo(
    () => new Map(sceneNodes.map((node, index) => [node.id, index])),
    [sceneNodes]);
  // A module is never drawn among its own members; highlighting one that is
  // not in the cloud would dim the whole cloud and light nothing.
  selectedRef.current = !graphBlocked && selectedNode &&
    nodeIndexMap.has(selectedNode.id) ? selectedNode.id : null;
  const linksRef = useRef(sceneLinks);
  linksRef.current = sceneLinks;
  const nodeIndexMapRef = useRef(nodeIndexMap);
  nodeIndexMapRef.current = nodeIndexMap;

  // Drops a selection the filters removed. A module is an aggregate this UI
  // builds rather than a loaded node, so it is never in this set and must not
  // be cleared by it.
  useEffect(() => {
    if (!selectedNode) return;
    const loaded = nodes.some((node) => node.id === selectedNode.id);
    if (loaded && !baseNodes.some((node) => node.id === selectedNode.id)) {
      setSelectedNode(null);
    }
  }, [baseNodes, nodes, selectedNode, setSelectedNode]);

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

  // Navigation is the canvas's to decide; the interaction hook keeps the
  // camera and the selection. Reading a node leaves the cloud alone.
  const openNode = useCallback((node: typeof sceneNodes[number]) => {
    const target = openTarget(node);
    if (target.kind === "node") return setExpandedNode(target.nodeId);
    setExpandedGroup(target.groupKey);
    setHudMode3d("FOCUS");
  }, [setExpandedGroup, setExpandedNode, setHudMode3d]);
  const navigateOnActivate = useCallback(
    (node: typeof sceneNodes[number], open: boolean) => {
      if (open) openNode(node);
      // Never handled here: the first click always reads the node.
      return false;
    }, [openNode]);

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
    navigateOnActivate,
  );
  useGraph3DCameraFrame(camRef, physicsNodesRef,
    cameraSceneKey({ repoIds, viewMode, focusNodeId, expandedGroup, layout: layout3d }),
    sceneNodes.length);
  // Aims at the selection after the rebuild above has placed it, so the look
  // target never trails a coordinate the node has already left.
  useEffect(() => {
    const selectedId = selectedNode?.id;
    if (!selectedId) return;
    const placed = physicsNodesRef.current.find((node) => node.id === selectedId);
    if (placed) camRef.current.targetLook.set(placed.x, placed.y, placed.z);
  }, [camRef, sceneNodes, selectedNode?.id]);
  const onSelectNodeId = useCallback(
    (nodeId: string, pathMode = false, open = false) => {
      const pn = physicsNodesRef.current.find((n) => n.id === nodeId);
      if (pn) activateNode(pn, pathMode, open);
    }, [activateNode]);

  const { threeRef, labelPoolRef, clusterPoolRef, tooltipRef } = useGraph3DSceneLifecycle({
    containerRef,
    camRef,
    onSelectNode: onSelectNodeId,
  });

  const openedLabel = sceneNodes.find((node) => node.id === openedNodeId)?.label ?? null;
  const navigateBack = useGraphBackNavigation({
    onClearNode: onClearFocus,
    onClearGroup: () => setHudMode3d("OVERVIEW"),
  });
  useGraph3DShortcuts({
    toggleShowLabels,
    onOpenSelected: () => selectedNode && openNode(selectedNode),
    onBack: navigateBack,
    containerRef,
  });

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
        {openedLabel
          ? `Opened ${openedLabel}, ${sceneNodes.length} displayed nodes`
          : expandedGroup
            ? `Module ${expandedGroup}, ${sceneNodes.length} displayed nodes`
            : `3D ${viewMode} grouped overview`}
      </span>
      <GraphContextBar
        projectionMode={projectionMode}
        viewMode={viewMode}
        expandedGroup={expandedGroup}
        openedLabel={openedLabel}
        hasSelection={Boolean(selectedNode)}
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
