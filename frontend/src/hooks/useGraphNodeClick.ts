import { useCallback, useRef } from "react";

import type { GraphNode } from "@/lib/types";
import {
  isSecondClick, nodeClickGesture, openTarget, type ClickMemory,
} from "@/lib/graphNodeGesture";

interface Options {
  onSelect: (node: GraphNode) => void;
  onOpenNode: (nodeId: string) => void;
  onOpenGroup: (groupKey: string) => void;
}

/**
 * Turns force-graph's node clicks into the two requests they can mean.
 *
 * The event arrives from `pointerup`, so the browser's click count is not on
 * it; the second click is recognised from the node and the clock instead.
 */
export function useGraphNodeClick({ onSelect, onOpenNode, onOpenGroup }: Options) {
  const lastClickRef = useRef<ClickMemory | null>(null);
  const groupOpenedAtRef = useRef(0);

  const openNode = useCallback((node: GraphNode) => {
    const target = openTarget(node);
    if (target.kind === "group") onOpenGroup(target.groupKey);
    else onOpenNode(target.nodeId);
  }, [onOpenGroup, onOpenNode]);

  const handleNodeClick = useCallback((node: GraphNode, event: { timeStamp: number }) => {
    const second = isSecondClick(lastClickRef.current, node.id, event.timeStamp);
    lastClickRef.current = { nodeId: node.id, at: event.timeStamp };
    const gesture = nodeClickGesture(
      node, second, event.timeStamp, groupOpenedAtRef.current);
    if (gesture.kind === "ignore") return;
    if (gesture.kind === "open-group") {
      groupOpenedAtRef.current = event.timeStamp;
      onOpenGroup(gesture.groupKey);
      return;
    }
    onSelect(node);
    if (gesture.kind === "select-and-open") onOpenNode(node.id);
  }, [onOpenGroup, onOpenNode, onSelect]);

  return { handleNodeClick, openNode };
}
