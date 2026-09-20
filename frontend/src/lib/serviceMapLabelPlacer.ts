/** Which service labels get drawn when they cannot all fit.
 *
 * Labels paint at a constant on-screen size while the layout is measured in
 * graph units, so how much room a label has is decided by the fitted zoom
 * rather than by anything the layout can arrange. At the zoom a 55-node estate
 * settles on, a 180px label spans ~1400 graph units against a ~590-unit link
 * distance: a name is wider than the gap between the services it joins, and no
 * force tuning closes that. Measured on that map, 47 of 55 labels overlapped
 * another, which is worse than a missing label — overlapping text reads as
 * belonging to whichever node the eye pairs it with.
 *
 * So the labels are placed the way a map places place-names: in priority
 * order, each one taken only if its box is still clear. This is the same
 * decision `graph3dLabelPlacer` makes for the 3D scene, kept separate because
 * that one works in screen coordinates over a DOM pool and this one in graph
 * units inside a canvas paint — they would not change together.
 *
 * The result is self-correcting as the reader zooms: boxes stay the same size
 * on screen while the distances between them grow, so labels that lost at the
 * fitted zoom reappear on the way in.
 */

export interface LabelCandidate {
  id: string;
  /** Label box in graph units, as the painter will draw it. */
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** Higher wins a contested box. Ties break on id, so placement is stable. */
  priority: number;
  /** Drawn whatever it overlaps — the reader asked for this one by name. */
  pinned?: boolean;
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

function overlaps(a: Box, b: Box): boolean {
  return a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
}

/** Labels are uniform in height, so banding by row keeps this near-linear
 * instead of comparing every box against every box already placed. */
function bandsOf(box: Box, bandHeight: number): number[] {
  const first = Math.floor(box.y0 / bandHeight);
  const last = Math.floor(box.y1 / bandHeight);
  const bands = [];
  for (let band = first; band <= last; band++) bands.push(band);
  return bands;
}

export function chooseServiceLabels(candidates: readonly LabelCandidate[]): Set<string> {
  if (candidates.length === 0) return new Set();

  const ordered = [...candidates].sort((a, b) => {
    if (!!b.pinned !== !!a.pinned) return b.pinned ? 1 : -1;
    if (b.priority !== a.priority) return b.priority - a.priority;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  // One band per label height; a box spans at most two of them.
  const bandHeight = Math.max(
    ...candidates.map((c) => c.y1 - c.y0), Number.MIN_VALUE);
  const placed = new Map<number, Box[]>();
  const chosen = new Set<string>();

  for (const candidate of ordered) {
    const bands = bandsOf(candidate, bandHeight);
    const clear = candidate.pinned
      || bands.every((band) =>
        (placed.get(band) ?? []).every((box) => !overlaps(candidate, box)));
    if (!clear) continue;
    chosen.add(candidate.id);
    for (const band of bands) {
      const bucket = placed.get(band);
      if (bucket) bucket.push(candidate);
      else placed.set(band, [candidate]);
    }
  }
  return chosen;
}
