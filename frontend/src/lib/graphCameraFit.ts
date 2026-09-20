export interface GraphBbox {
  x: [number, number];
  y: [number, number];
}

export interface Viewport {
  width: number;
  height: number;
}

export interface FitTarget {
  x: number;
  y: number;
  zoom: number;
}

/**
 * How far the automatic fit may zoom in.
 *
 * Framing is bounded by what is drawn, and a module can hold a single file:
 * fitting that one node to the viewport scales it to ~67x, which fills the
 * screen with one disc and reads as a bug. Past this point more zoom adds no
 * information, so the fit stops and the scene simply sits in the middle.
 */
export const MAX_FIT_ZOOM = 2.5;

/**
 * How far the automatic fit may zoom out.
 *
 * The other end of the same idea, and the one that costs something: below this
 * the fit stops shrinking and the scene is allowed to run past the edges of
 * the viewport, to be panned rather than taken in at a glance.
 *
 * That is the better trade. Labels and node discs are painted at a fixed size
 * in SCREEN pixels, so zooming out buys nothing but crowding — at 0.3 a
 * bounded 180px label already spans 600 graph units, more than a settled
 * layout puts between two linked services. Past that point a map that "fits"
 * is one whose labels have been dropped and whose nodes sit inside one
 * another; showing part of it legibly is worth more than all of it as a smudge.
 */
export const MIN_FIT_ZOOM = 0.3;

export function fitTarget(
  bbox: GraphBbox | null | undefined,
  viewport: Viewport,
  padding: number,
): FitTarget | null {
  if (!bbox) return null;
  const usableWidth = viewport.width - padding * 2;
  const usableHeight = viewport.height - padding * 2;
  if (usableWidth <= 0 || usableHeight <= 0) return null;
  // A single node has no extent of its own; treat it as a point rather than
  // dividing by zero.
  const spanX = Math.max(bbox.x[1] - bbox.x[0], 1);
  const spanY = Math.max(bbox.y[1] - bbox.y[0], 1);
  return {
    x: (bbox.x[0] + bbox.x[1]) / 2,
    y: (bbox.y[0] + bbox.y[1]) / 2,
    zoom: Math.max(
      MIN_FIT_ZOOM,
      Math.min(MAX_FIT_ZOOM, usableWidth / spanX, usableHeight / spanY),
    ),
  };
}
