import { useCallback, useMemo, useRef } from "react";

import { placeLabels } from "@/lib/canvasLabelSpace";
import { serviceLabelBox } from "@/lib/serviceMapPainter";
import { MAX_SERVICE_LABEL_PX } from "@/lib/serviceMapLabel";

interface LabelledGraph {
  nodes: any[];
  links: any[];
}

export interface ServiceMapLabels {
  /** Ids the placer kept for the frame about to be painted. */
  shown: { current: Set<string> };
  /** Runs once per frame, before any node is painted. */
  place: (ctx: CanvasRenderingContext2D, globalScale: number) => void;
}

/**
 * Decides which service labels are drawn on the frame about to be painted.
 *
 * Whether a label fits depends on every other label, so it cannot be settled
 * inside the per-node paint callback, which sees one node at a time. It is
 * settled here instead and the paint reads the answer.
 *
 * `canvasLabelSpace` owns the fitting; what this hook contributes is the
 * service map's own idea of which label deserves a contested spot.
 *
 * The result lives in a ref, not in state: it is recomputed every frame, and
 * setting state per frame would re-render the canvas out from under itself.
 */
export function useServiceMapLabels(
  graphData: LabelledGraph,
  displayNames: Map<string, string>,
  focusId: string | undefined,
  hoverId: string | undefined,
): ServiceMapLabels {
  const shown = useRef<Set<string>>(new Set());

  /** In a crowded region the hub is the one worth naming, and a gateway
   * outranks its own degree because it is where reading starts. */
  const priority = useMemo(() => {
    const degree = new Map<string, number>();
    for (const link of graphData.links) {
      for (const end of [link.source, link.target]) {
        const id = typeof end === "object" ? end?.id : end;
        if (id != null) degree.set(id, (degree.get(id) ?? 0) + 1);
      }
    }
    return new Map(graphData.nodes.map((node) =>
      [node.id, (degree.get(node.id) ?? 0) + (node.is_gateway ? 1000 : 0)]));
  }, [graphData]);

  const place = useCallback((ctx: CanvasRenderingContext2D, globalScale: number) => {
    shown.current = placeLabels(
      graphData.nodes
        .filter((node) => node.x != null && node.y != null)
        .map((node) => {
          const pill = serviceLabelBox(
            node, ctx, globalScale,
            displayNames.get(node.id) ?? node.name, MAX_SERVICE_LABEL_PX);
          return {
            id: node.id,
            rect: pill.rect,
            priority: priority.get(node.id) ?? 0,
            pinned: node.id === focusId || node.id === hoverId,
          };
        }));
  }, [graphData, displayNames, priority, focusId, hoverId]);

  return { shown, place };
}
