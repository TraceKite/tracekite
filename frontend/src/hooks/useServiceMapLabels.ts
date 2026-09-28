import { useCallback, useMemo, useRef } from "react";

import { placeLabels } from "@/lib/canvasLabelSpace";
import type { LabelBid } from "@/lib/canvasLabelSpace";
import type { LabelPill } from "@/lib/canvasLabelPill";
import { serviceLabelBox } from "@/lib/serviceMapPainter";
import { MAX_SERVICE_LABEL_PX } from "@/lib/serviceMapLabel";
import { serviceLabelBid, serviceLabelRanks } from "@/lib/serviceMapLabelRank";

interface LabelledGraph {
  nodes: any[];
  links: any[];
}

/** Where the reader's attention is, which decides who keeps a contested spot. */
export interface LabelAttention {
  focusId?: string;
  hoverId?: string;
  /** The focused service and its neighbours; null when nothing is focused. */
  lit: ReadonlySet<string> | null;
}

export interface ServiceMapLabels {
  /** Runs before each frame is painted, so that frame places afresh. */
  beginFrame: () => void;
  /** The label to draw for this node on this frame, or undefined when it lost
   * its spot. The first call in a frame places every label. */
  placedLabel: (node: any, ctx: CanvasRenderingContext2D, globalScale: number)
    => LabelPill | undefined;
}

interface FramePlacement {
  placed: boolean;
  pills: Map<string, LabelPill>;
}

/**
 * Decides which service labels are drawn on each frame.
 *
 * Whether a label fits depends on every other label, so it cannot be settled
 * one node at a time. It is settled on the frame's first node paint instead,
 * not in onRenderFramePre: force-graph calls that before it ticks the layout,
 * so while the map was still moving every label was tested at one position
 * and drawn at the next. The pills measured here are the ones painted, which
 * also means each label is fitted to its budget once a frame, not twice.
 *
 * `canvasLabelSpace` owns the fitting and `serviceMapLabelRank` the policy;
 * this hook only runs them at the right moment. The result lives in a ref, not
 * in state: it is recomputed every frame, and setting state per frame would
 * re-render the canvas out from under itself.
 */
export function useServiceMapLabels(
  graphData: LabelledGraph,
  displayNames: Map<string, string>,
  { focusId, hoverId, lit }: LabelAttention,
): ServiceMapLabels {
  const frame = useRef<FramePlacement>({ placed: false, pills: new Map() });
  const ranks = useMemo(
    () => serviceLabelRanks(graphData.nodes, graphData.links), [graphData]);

  const beginFrame = useCallback(() => { frame.current.placed = false; }, []);

  // Its identity changes whenever the answer could, which is also what makes
  // force-graph repaint: a new node painter is a redraw, a new pre-frame hook
  // is not.
  const placedLabel = useCallback((node: any, ctx: CanvasRenderingContext2D,
                                   globalScale: number) => {
    if (!frame.current.placed) {
      const context = { ranks, focusId, hoverId, lit };
      const pills = new Map<string, LabelPill>();
      const bids: LabelBid[] = [];
      // Measuring sets the font; the painters set their own.
      ctx.save();
      for (const each of graphData.nodes) {
        if (each.x == null || each.y == null) continue;
        const pill = serviceLabelBox(each, ctx, globalScale,
          displayNames.get(each.id) ?? each.name, MAX_SERVICE_LABEL_PX);
        pills.set(each.id, pill);
        bids.push(serviceLabelBid(each.id, pill.rect, context));
      }
      ctx.restore();
      const chosen = placeLabels(bids);
      for (const id of pills.keys()) if (!chosen.has(id)) pills.delete(id);
      frame.current = { placed: true, pills };
    }
    return frame.current.pills.get(node.id);
  }, [graphData, displayNames, ranks, focusId, hoverId, lit]);

  return { beginFrame, placedLabel };
}
