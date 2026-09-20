/** Where the services nothing links to are pinned.
 *
 * They are pinned rather than left to the simulation because a dozen nodes
 * with no edges have nothing to arrange them, and a force layout scatters them
 * through the gaps in the real graph where they read as part of it. Parked in
 * a block, they read as what they are: a list of services linking found no
 * edges for.
 *
 * A single row cannot be made to work, and the arithmetic says so rather than
 * the taste. `zoomToFit` fits the widest thing on the canvas to the viewport,
 * so if the row is that thing each isolate gets `viewportWidth / count` pixels
 * whatever spacing is chosen — widen the row and the fit shrinks the scale by
 * exactly the factor you widened it. Six repo-qualified names want ~900px of a
 * ~750px canvas, so four of the six lost their label and the row read as a
 * line of anonymous dots.
 *
 * Wrapping is what changes the arithmetic: three columns of two gives every
 * cell a third of the canvas instead of a sixth. So the column count comes
 * from how many bounded labels fit across the canvas — a screen-space
 * question, answered with screen-space numbers.
 *
 * That guarantee only holds while the block is the widest thing on the canvas,
 * because otherwise the graph sets the scale and the cells get whatever is
 * left. Sized as a flat share of the link distance the block lost that race at
 * every scope, and three of six labels went. So the block is sized against
 * what it is competing with: a force layout's extent grows with the square
 * root of its node count, so the block's does too, and the two stay comparable
 * from sixteen nodes to fifty-five.
 */

/** Clear space between one cell's label and the next. */
const LABEL_GUTTER_PX = 20;

/** Block width against `sqrt(nodes) * linkDistance`, which is roughly what a
 * settled force layout spans. Measured on this estate: 16 nodes came to ~0.77
 * of it and 55 to ~1.02, so a block at 0.9 sits alongside the graph rather
 * than being squeezed by it. */
const BLOCK_WIDTH_SHARE = 0.9;

/** Where the block starts below the graph, likewise. */
const BLOCK_TOP_SHARE = 180 / 220;

/** Rows are pitched tighter than columns: a label is far wider than it is tall. */
const ROW_PITCH_SHARE = 0.3;

export interface IsolateBlockOptions {
  count: number;
  /** Every node on the map, not just the isolates: what the block competes
   * with for the fitted zoom is the whole layout's extent. */
  nodeCount: number;
  /** The layout's link distance, which the block scales itself against. */
  linkDistance: number;
  canvasWidthPx: number;
  /** The widest a label is allowed to be drawn. */
  labelBudgetPx: number;
}

export interface IsolatePlacement {
  fx: number;
  fy: number;
}

/** How many cells fit across the canvas without their labels touching. */
export function isolateColumns(
  count: number,
  canvasWidthPx: number,
  labelBudgetPx: number,
): number {
  const across = Math.floor(canvasWidthPx / (labelBudgetPx + LABEL_GUTTER_PX));
  return Math.max(1, Math.min(count, across));
}

/**
 * One placement per isolate, in order, centred on the origin.
 *
 * Every row is centred on its own, so a short last row sits under the middle
 * of the block and the whole thing stays symmetric about zero — `zoomToFit`
 * otherwise favours whichever side the block leans towards.
 */
export function isolateBlock(
  { count, nodeCount, linkDistance, canvasWidthPx, labelBudgetPx }: IsolateBlockOptions,
): IsolatePlacement[] {
  if (count <= 0) return [];
  const columns = isolateColumns(count, canvasWidthPx, labelBudgetPx);
  const cellWidth =
    BLOCK_WIDTH_SHARE * Math.sqrt(Math.max(nodeCount, 1)) * linkDistance / columns;
  const rowPitch = linkDistance * ROW_PITCH_SHARE;
  const top = linkDistance * BLOCK_TOP_SHARE;

  const placements: IsolatePlacement[] = [];
  for (let index = 0; index < count; index++) {
    const row = Math.floor(index / columns);
    const column = index % columns;
    const inThisRow = Math.min(columns, count - row * columns);
    placements.push({
      fx: (column - (inThisRow - 1) / 2) * cellWidth,
      fy: top + row * rowPitch,
    });
  }
  return placements;
}
