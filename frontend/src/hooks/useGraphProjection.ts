import { useCallback, useEffect, useMemo } from "react";

import type { GraphLink, GraphNode, ViewMode } from "@/lib/types";
import {
  activeNavigation,
  graphContextKey,
} from "@/lib/graphNavigation";
import {
  buildGroupDetail,
  buildModuleOverview,
  buildOneHopNeighborhood,
  buildBoundedImpact,
  usesGroupedEntry,
  type GraphProjection,
} from "@/lib/graphOverviewProjection";
import {
  endpointId,
  isLinkVisible,
  isNodeVisible,
} from "@/lib/graphVisibility";
import { graphGroupOf } from "@/lib/graphStyle";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";

interface Options {
  nodes: GraphNode[];
  links: GraphLink[];
  hiddenNodeTypes: string[];
  hiddenEdgeTypes: string[];
  hideLockfileDeps: boolean;
  connectionsOnly: boolean;
  /** Set when a search or the drawer fetched a graph around one node. */
  focusNodeId: string | null;
  viewMode: ViewMode;
  scopeKey: string;
  detailNodeLimit: number;
}

export type ProjectionMode = "overview" | "group" | "focus" | "exact";

export function useGraphProjection({
  nodes,
  links,
  hiddenNodeTypes,
  hiddenEdgeTypes,
  hideLockfileDeps,
  connectionsOnly,
  focusNodeId,
  viewMode,
  scopeKey,
  detailNodeLimit,
}: Options) {
  const navigation = useGraphNavigationStore();
  const contextKey = graphContextKey(scopeKey ? scopeKey.split(",") : [], viewMode);
  const { expandedGroup, expandedNodeId } = activeNavigation(navigation, contextKey);
  const setExpandedGroup = useCallback((group: string | null) => {
    navigation.setExpandedGroup(group, contextKey);
  }, [contextKey, navigation.setExpandedGroup]);
  const setExpandedNode = useCallback((nodeId: string | null) => {
    navigation.setExpandedNode(nodeId, contextKey);
  }, [contextKey, navigation.setExpandedNode]);

  useEffect(() => navigation.syncContext(contextKey), [contextKey, navigation.syncContext]);

  const base = useMemo<GraphProjection>(() => {
    const allowed = nodes.filter((node) =>
      isNodeVisible(node, hiddenNodeTypes, hideLockfileDeps));
    const crossingNodes = new Set<string>();
    if (connectionsOnly) {
      for (const link of links) {
        if (link.type !== "INVOKES" && link.type !== "EXPOSES") continue;
        crossingNodes.add(endpointId(link.source));
        crossingNodes.add(endpointId(link.target));
      }
    }
    const visibleNodes = connectionsOnly
      ? allowed.filter((node) => crossingNodes.has(node.id))
      : allowed;
    const ids = new Set(visibleNodes.map((node) => node.id));
    return {
      nodes: visibleNodes,
      links: links.filter((link) => isLinkVisible(link, hiddenEdgeTypes, ids)),
    };
  }, [connectionsOnly, hiddenEdgeTypes, hiddenNodeTypes, hideLockfileDeps,
      links, nodes]);

  // Opening a node on the canvas and fetching a graph around one are the same
  // request — draw that node's neighborhood. Selecting a node is not: it fills
  // the details drawer and leaves the canvas where the reader put it.
  const openedNodeId = expandedNodeId ?? focusNodeId;

  const result = useMemo(() => {
    const openedLoaded = openedNodeId &&
      base.nodes.some((node) => node.id === openedNodeId);
    if (openedLoaded) {
      return {
        projection: viewMode === "impact"
          ? buildBoundedImpact(base.nodes, base.links, openedNodeId, detailNodeLimit)
          : buildOneHopNeighborhood(base.nodes, base.links, openedNodeId, detailNodeLimit),
        mode: "focus" as ProjectionMode,
      };
    }
    if (expandedGroup && base.nodes.some((node) => graphGroupOf(node) === expandedGroup)) {
      return {
        projection: buildGroupDetail(base.nodes, base.links, expandedGroup, detailNodeLimit),
        mode: "group" as ProjectionMode,
      };
    }
    if (usesGroupedEntry(viewMode)) {
      return {
        projection: buildModuleOverview(base.nodes, base.links),
        mode: "overview" as ProjectionMode,
      };
    }
    return { projection: base, mode: "exact" as ProjectionMode };
  }, [base, detailNodeLimit, expandedGroup, openedNodeId, viewMode]);

  return {
    baseNodes: base.nodes,
    baseLinks: base.links,
    visibleNodes: result.projection.nodes,
    visibleLinks: result.projection.links,
    projectedTotalNodeCount: result.projection.totalNodeCount ?? result.projection.nodes.length,
    projectionMode: result.mode,
    expandedGroup,
    setExpandedGroup,
    openedNodeId,
    setExpandedNode,
  };
}
