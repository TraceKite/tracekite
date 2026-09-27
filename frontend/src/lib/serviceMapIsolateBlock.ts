/** Where the services nothing links to are pinned.
 *
 * They are pinned rather than left to the simulation because a dozen nodes
 * with no edges have nothing to arrange them, and a force layout scatters them
 * through the gaps in the real graph where they read as part of it. Parked in
 * a block below the graph, they read as what they are: a list of services
 * linking found no edges for.
 *
 * A single row cannot be made to work, and the arithmetic says so rather than
 * the taste. The fit scales the widest thing on the canvas to the viewport,
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
 *
 * Its top works the same way until the layout has run, and from then on is
 * measured rather than estimated: a top that scaled with the link distance
 * alone left all seven isolates of the 55-node estate inside the graph, where
 * the whole point of the block was lost.
 */

/** Clear space between one cell's label and the next. */
const LABEL_GUTTER_PX = 20;

/** Block width against `sqrt(nodes) * linkDistance`, which is roughly what a
 * settled force layout spans. Measured on this estate: 16 nodes came to ~0.77
 * of it and 55 to ~1.02, so a block at 0.9 sits alongside the graph rather
 * than being squeezed by it. */
const BLOCK_WIDTH_SHARE = 0.9;

/** Where the block starts before the layout has run, against the same extent.
 * A settled estate reaches about 0.38 of it below the centre on a landscape
 * canvas, so this starts the block just clear of the graph it will sit under. */
const BLOCK_TOP_SHARE = 0.45;

/** Clearance between the graph's lowest node and the block, once measured:
 * room for that node's own label and the first row's. */
const BLOCK_GAP_SHARE = 0.6;

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
  /** The linked graph as laid out; omitted before the layout has run. */
  graph?: GraphExtent;
  /** How the canvas will be framed; with `graph`, it lets the cells be sized
   * for the zoom the fit will actually pick. */
  framing?: IsolateFraming;
}

/** Where the linked graph's nodes reach, in graph units. */
export interface GraphExtent {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface IsolateFraming {
  canvasHeightPx: number;
  paddingPx: number;
  minZoom: number;
  maxZoom: number;
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
 * The narrowest cell whose label keeps its whole budget at the fitted zoom.
 *
 * The share-of-extent width assumes the block is what the fit is bound by. It
 * often is not: under a tall graph the fit is bound by the height, the cells
 * get whatever pixels that zoom leaves them, and two petclinic repos lost two
 * of six isolate names that way once the block moved below the graph. So the
 * zoom is worked out as the fit will work it out — the graph's width against
 * the whole scene's height — and each cell is given its label's budget at it.
 * If that makes the block the widest thing instead, the fit is bound by the
 * block, and the column count already gives every cell its share.
 */
function legibleCellWidth(
  graph: GraphExtent,
  blockBottom: number,
  { canvasWidthPx, labelBudgetPx, framing }: Required<Pick<IsolateBlockOptions,
    "canvasWidthPx" | "labelBudgetPx" | "framing">>,
): number {
  const usableWidth = canvasWidthPx - framing.paddingPx * 2;
  const usableHeight = framing.canvasHeightPx - framing.paddingPx * 2;
  if (usableWidth <= 0 || usableHeight <= 0) return 0;
  const zoom = Math.max(framing.minZoom, Math.min(
    framing.maxZoom,
    usableWidth / Math.max(graph.right - graph.left, 1),
    usableHeight / Math.max(blockBottom - graph.top, 1),
  ));
  return (labelBudgetPx + LABEL_GUTTER_PX) / zoom;
}

/**
 * One placement per isolate, in order, centred under the graph.
 *
 * Every row is centred on its own, so a short last row sits under the middle
 * of the block and the whole thing stays symmetric about the graph's centre —
 * the fit otherwise favours whichever side the block leans towards.
 */
export function isolateBlock(options: IsolateBlockOptions): IsolatePlacement[] {
  const { count, nodeCount, linkDistance, canvasWidthPx, labelBudgetPx, graph, framing } =
    options;
  if (count <= 0) return [];
  const columns = isolateColumns(count, canvasWidthPx, labelBudgetPx);
  const extent = Math.sqrt(Math.max(nodeCount, 1)) * linkDistance;
  const rowPitch = linkDistance * ROW_PITCH_SHARE;
  const top = graph
    ? graph.bottom + linkDistance * BLOCK_GAP_SHARE
    : extent * BLOCK_TOP_SHARE;
  const bottom = top + (Math.ceil(count / columns) - 1) * rowPitch;
  const cellWidth = Math.max(
    BLOCK_WIDTH_SHARE * extent / columns,
    graph && framing
      ? legibleCellWidth(graph, bottom, { canvasWidthPx, labelBudgetPx, framing })
      : 0,
  );
  const centerX = graph ? (graph.left + graph.right) / 2 : 0;
  return gridCells(count, columns, { centerX, top, cellWidth, rowPitch });
}

interface Grid {
  centerX: number;
  top: number;
  cellWidth: number;
  rowPitch: number;
}

/* Every row is centred on its own, so a short last row sits in the middle. */
function gridCells(count: number, columns: number, grid: Grid): IsolatePlacement[] {
  const placements: IsolatePlacement[] = [];
  for (let index = 0; index < count; index++) {
    const row = Math.floor(index / columns);
    const column = index % columns;
    const inThisRow = Math.min(columns, count - row * columns);
    placements.push({
      fx: grid.centerX + (column - (inThisRow - 1) / 2) * grid.cellWidth,
      fy: grid.top + row * grid.rowPitch,
    });
  }
  return placements;
}
