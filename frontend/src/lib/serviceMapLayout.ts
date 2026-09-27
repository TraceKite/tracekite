/** Force-layout and framing settings for the service map.
 *
 * The map paints nodes at a fixed size in SCREEN pixels but lays them out in
 * graph units, and the fit then picks whatever zoom makes the whole thing fit.
 * Those three facts interact: the more nodes there are, the wider the layout,
 * the smaller the fitted zoom — and the more graph units a 9px disc covers. A
 * link distance that reads well at 20 nodes puts 55 nodes inside one another's
 * discs, which is how a map with every one of its 64 links drawn still showed
 * almost none of them.
 *
 * So link distance grows with the node count rather than shrinking, spending
 * graph units the fit is about to make cheaper. The view also pens the layout
 * in with forceX/forceY, as the repo graph next door does: a centre force alone
 * moves a cloud without compacting it, and the fitted zoom sat at 0.13.
 *
 * The collide radius is what stops two discs sharing a spot, and its size is
 * the whole story. Sized to the link distance it is a uniform expansion, and
 * the fit gives uniform expansions straight back: at 0.32 of the link distance
 * the median drawn link FELL from 35px to 31px. Sized to the discs it has to
 * separate — 0.13, about two 9px radii at the zoom a fitted estate settles on —
 * it only acts where nodes genuinely touch. When it was introduced, disc
 * overlaps went from 8 to 0 and labels drawn from 26 to 29.
 *
 * Weaker charge (-300, what the repo graph uses) let the map's many
 * disconnected components pile into the middle. That was measured before the
 * layout was penned in, and has not been re-measured since.
 */

import type { CameraFraming } from "./graphCameraFit.ts";

/**
 * How the service map is framed.
 *
 * The zoom floor is the part that costs something: below it the fit stops
 * shrinking and the map is allowed to run past the edges of the viewport, to be
 * panned rather than taken in at a glance. That is the better trade here
 * because labels and discs are painted at a fixed size in SCREEN pixels, so
 * zooming out buys nothing but crowding — at 0.3 a bounded 180px label already
 * spans 600 graph units, more than a settled layout puts between two linked
 * services. It is this map's floor, not every canvas's: the reasoning is about
 * service labels, and the repo graph is still framed whole.
 */
export const SERVICE_MAP_FRAMING: CameraFraming = {
  padding: 90,
  minZoom: 0.3,
  durationMs: 400,
};

export interface ServiceMapForces {
  chargeStrength: number;
  chargeDistanceMax: number;
  linkDistance: number;
  centerStrength: number;
  /** Graph-unit radius no two nodes may overlap, linked or not. */
  collideRadius: number;
}

/** Graph units of link distance per node on the map, and the floor it adds to.
 *
 * Tuned with the layout penned in, which compacts the cloud and raises the
 * fitted zoom, so the same on-screen length needs fewer graph units than it
 * did before: 38 nodes get 196, 55 get 230. A threshold with a flat value below
 * it was the first attempt and was wrong — at 38 nodes, one short of it,
 * thirty of the sixty-eight drawn lines were under ten pixels. The crowding
 * does not start at a particular size; it comes on steadily, so the answer has
 * to as well. */
const LINK_DISTANCE_BASE = 120;
const LINK_DISTANCE_PER_NODE = 2;

/** Not a tuned value — a stop so a pathological node count cannot run away. */
const MAX_LINK_DISTANCE = 1200;

/** Share of the link distance a node keeps to itself: roughly the two 9px
 * radii that would otherwise overlap, at the zoom a fitted estate settles on. */
const COLLIDE_SHARE = 0.13;

export function serviceMapForces(nodeCount: number): ServiceMapForces {
  const n = Math.max(nodeCount, 1);
  const linkDistance = Math.min(
    LINK_DISTANCE_BASE + n * LINK_DISTANCE_PER_NODE, MAX_LINK_DISTANCE);
  return {
    chargeStrength: -900,
    chargeDistanceMax: 1200,
    linkDistance,
    centerStrength: 0.05,
    collideRadius: linkDistance * COLLIDE_SHARE,
  };
}
