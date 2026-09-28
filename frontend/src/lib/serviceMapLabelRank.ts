/** Which service name deserves a contested spot on the service map.
 *
 * `canvasLabelSpace` decides whether a label fits; this is the service map's
 * policy for who wins when two want the same space. It lives apart from the
 * hook that runs it so the policy can be tested without a canvas or React.
 */

import type { LabelBid, LabelRect } from "./canvasLabelSpace.ts";

/** A gateway outranks any degree a service could reach: it is where reading
 * starts, and in a crowded region the hub is otherwise the one worth naming. */
const GATEWAY_RANK = 1_000;

/** While a service is focused, everything outside its neighbourhood is painted
 * at a fraction of its opacity. Such a label still bids, but only for space no
 * lit label wants — ranked on degree alone, a hub drawn at 12% took the spot
 * of the very neighbour the reader had focused the service to see. */
const DIMMED_RANK = -1_000_000;

interface RankedNode {
  id: string;
  is_gateway?: boolean;
}

interface RankedLink {
  source: unknown;
  target: unknown;
}

/* Links arrive with string endpoints and force-graph swaps them for the node
 * objects once drawn, so both are read. */
function endpointId(end: unknown): string | undefined {
  if (typeof end === "string") return end;
  if (end != null && typeof end === "object") return (end as { id?: string }).id;
  return undefined;
}

/** Degree, with gateways lifted above every degree. */
export function serviceLabelRanks(
  nodes: readonly RankedNode[],
  links: readonly RankedLink[],
): Map<string, number> {
  const degree = new Map<string, number>();
  for (const link of links) {
    for (const end of [link.source, link.target]) {
      const id = endpointId(end);
      if (id != null) degree.set(id, (degree.get(id) ?? 0) + 1);
    }
  }
  return new Map(nodes.map((node) =>
    [node.id, (degree.get(node.id) ?? 0) + (node.is_gateway ? GATEWAY_RANK : 0)]));
}

export interface LabelContext {
  ranks: ReadonlyMap<string, number>;
  /** Pinned: drawn whatever they land on. */
  focusId?: string;
  hoverId?: string;
  /** The focused service and its neighbours; null when nothing is focused. */
  lit: ReadonlySet<string> | null;
}

export function serviceLabelBid(id: string, rect: LabelRect, context: LabelContext): LabelBid {
  const dimmed = context.lit != null && !context.lit.has(id);
  return {
    id,
    rect,
    priority: (context.ranks.get(id) ?? 0) + (dimmed ? DIMMED_RANK : 0),
    pinned: id === context.focusId || id === context.hoverId,
  };
}
