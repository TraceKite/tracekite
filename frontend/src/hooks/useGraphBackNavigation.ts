import { useCallback } from "react";

import { useGraphStore } from "@/store/graphStore";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";

interface Options {
  onClearNode?: () => void;
  onClearGroup?: () => void;
}

export function useGraphBackNavigation({ onClearNode, onClearGroup }: Options = {}) {
  const {
    selectedEdge, selectedNode, activePath3d, focusNodeId, viewMode,
    setSelectedEdge, setSelectedNode, setActivePath3d, setFocusNode,
    setSearchQuery, setViewMode,
  } = useGraphStore();
  const { expandedGroup, clearExpandedGroup } = useGraphNavigationStore();

  return useCallback(() => {
    if (activePath3d) {
      setActivePath3d(null);
      return;
    }
    if (selectedEdge) {
      setSelectedEdge(null);
      return;
    }
    if (selectedNode) {
      onClearNode ? onClearNode() : setSelectedNode(null);
      if (focusNodeId) setFocusNode(null);
      setSearchQuery("");
      if (viewMode === "impact") setViewMode("overview");
      return;
    }
    if (expandedGroup) {
      clearExpandedGroup();
      onClearGroup?.();
    }
  }, [activePath3d, clearExpandedGroup, expandedGroup, focusNodeId,
      onClearGroup, onClearNode, selectedEdge, selectedNode, setActivePath3d, setFocusNode,
      setSearchQuery, setSelectedEdge, setSelectedNode, setViewMode, viewMode]);
}
