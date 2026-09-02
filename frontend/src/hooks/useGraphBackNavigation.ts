import { useCallback } from "react";

import { openTarget } from "@/lib/graphNodeGesture";
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
  const { expandedGroup, expandedNodeId, clearExpandedGroup, clearExpandedNode } =
    useGraphNavigationStore();

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
      // Reading a thing and having opened it are one step when they name the
      // same thing — the reader took one action and expects one to undo it.
      const target = openTarget(selectedNode);
      const readingWhatIsOpen = target.kind === "group"
        ? expandedGroup === target.groupKey
        : expandedNodeId === target.nodeId;
      onClearNode ? onClearNode() : setSelectedNode(null);
      if (focusNodeId) setFocusNode(null);
      setSearchQuery("");
      if (viewMode === "impact") setViewMode("overview");
      if (readingWhatIsOpen) {
        if (target.kind === "group") {
          clearExpandedGroup();
          onClearGroup?.();
        } else clearExpandedNode();
      }
      return;
    }
    if (expandedNodeId) {
      clearExpandedNode();
      return;
    }
    if (expandedGroup) {
      clearExpandedGroup();
      onClearGroup?.();
    }
  }, [activePath3d, clearExpandedGroup, clearExpandedNode, expandedGroup,
      expandedNodeId, focusNodeId, onClearGroup, onClearNode, selectedEdge,
      selectedNode, setActivePath3d, setFocusNode, setSearchQuery,
      setSelectedEdge, setSelectedNode, setViewMode, viewMode]);
}
