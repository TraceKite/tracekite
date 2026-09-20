/** Where a link's line starts and ends once both node discs are cleared.
 *
 * Every canvas in the app draws edges between round nodes and so needs this,
 * and all three had their own version with three different answers to the one
 * case that matters — a link shorter than the clearances trimming it. The repo
 * graph capped the trim at 45% of the length, the service map refused to draw,
 * and the trace canvas refuses to this day. One decision, one implementation.
 *
 * Every length the map paints is screen-space, so the clearances arrive in
 * pixels and are divided by the zoom to reach graph units. They are screen-space
 * for a reason worth keeping: a fixed graph-unit gap of 12 was tuned for one
 * zoom level, and fitting a small map opened a canyon between the arrowhead and
 * the node while zooming out buried the arrowhead inside it.
 *
 * But that divide is also why this needs its own rule: as the view zooms out the
 * clearances GROW in graph units while the layout's link distance stays fixed,
 * so below some zoom the two clearances are longer than the link they trim.
 *
 * Refusing to draw that link is the wrong answer. A fitted 55-node map settles
 * at ~0.15 zoom, where the clearances come to ~168 graph units against a
 * ~130-unit link distance — 49 of its 64 edges silently disappeared while the
 * status bar went on counting all 64. A link too short for its clearances is a
 * crowded link, not an absent one, so the clearances shrink to fit and the
 * line is always drawn.
 */

export interface LinkPoint {
  x: number;
  y: number;
}

export interface LinkTrim {
  /** Clearance from each node's centre, in screen pixels. */
  startClearancePx: number;
  endClearancePx: number;
  /** Arrowhead length in screen pixels. */
  arrowPx: number;
  /** Canvas zoom, converting those pixels to the graph units a node sits in.
   * Pass 1 where the clearances are already graph units, as the repo graph's
   * node radii are. */
  globalScale: number;
}

export interface LinkLine {
  sx: number;
  sy: number;
  ex: number;
  ey: number;
  /** Graph-unit arrowhead, shrunk when the line left over cannot seat it. */
  arrowLength: number;
}

/** Share of the centre-to-centre span that stays drawn however tight the zoom. */
const MIN_VISIBLE_FRACTION = 0.3;

/** An arrowhead longer than half its line reads as a triangle, not a direction. */
const MAX_ARROW_FRACTION = 0.5;

export function trimLinkToNodes(
  start: LinkPoint,
  end: LinkPoint,
  trim: LinkTrim,
): LinkLine | null {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const len = Math.hypot(dx, dy);
  // Coincident nodes give no direction to draw along; everything else does.
  if (!(len > 0) || !(trim.globalScale > 0)) return null;

  const wanted = (trim.startClearancePx + trim.endClearancePx) / trim.globalScale;
  const budget = len * (1 - MIN_VISIBLE_FRACTION);
  const shrink = wanted > budget ? budget / wanted : 1;
  const startGap = (trim.startClearancePx / trim.globalScale) * shrink;
  const endGap = (trim.endClearancePx / trim.globalScale) * shrink;

  const ux = dx / len;
  const uy = dy / len;
  return {
    sx: start.x + ux * startGap,
    sy: start.y + uy * startGap,
    ex: end.x - ux * endGap,
    ey: end.y - uy * endGap,
    arrowLength: Math.min(
      trim.arrowPx / trim.globalScale,
      (len - startGap - endGap) * MAX_ARROW_FRACTION,
    ),
  };
}
