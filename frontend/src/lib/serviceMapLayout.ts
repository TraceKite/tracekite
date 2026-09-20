/** Force-layout settings for the service map, chosen by how much is on it.
 *
 * The map paints nodes at a fixed size in SCREEN pixels but lays them out in
 * graph units, and `zoomToFit` then picks whatever zoom makes the whole thing
 * fit. Those three facts interact: the more nodes there are, the wider the
 * layout, the smaller the fitted zoom — and the more graph units a 9px disc
 * covers. A link distance that reads well at 20 nodes puts 55 nodes inside one
 * another's discs, which is how a map with every one of its 64 links drawn
 * still showed almost none of them.
 *
 * So link distance grows with the node count rather than shrinking, spending
 * graph units that the fit is about to make cheaper. Measured on the 55-node
 * estate: at the old 130 only 15 of 64 links were long enough to draw at all;
 * at 590 every one draws, the median is ~60px and none are under ten.
 *
 * The collide radius is what stops two discs sharing a spot, and its size is
 * the whole story. Sized to the link distance it is a uniform expansion, and
 * `zoomToFit` gives uniform expansions straight back: at 0.32 of the link
 * distance the median drawn link FELL from 35px to 31px and the count under
 * ten pixels rose from three to ten. Sized to the discs it has to separate —
 * 0.13, about two 9px radii at the zoom a fitted estate settles on — it only
 * acts where nodes genuinely touch, and every measure improves at once: disc
 * overlaps 8 to 0, labels drawn 26 to 29, median link 62px to 65px.
 *
 * Weaker charge is the one that really does not work, though it is what the
 * repo graph next door uses. That one is penned in by forceX/forceY; this map
 * is not, and at -300 its many disconnected components piled into the middle.
 */

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
 * Measured on this estate, holding the median drawn link near 60 screen pixels
 * at the fitted zoom: 38 nodes need ~480 units, 55 need ~580. A threshold with
 * a flat value below it was the first attempt and was wrong — at 38 nodes, one
 * short of it, thirty of the sixty-eight drawn lines were still under ten
 * pixels. The crowding does not start at a particular size; it comes on
 * steadily, so the answer has to as well. */
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
