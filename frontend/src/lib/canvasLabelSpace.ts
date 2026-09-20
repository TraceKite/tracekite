/** Whether a label has room, for every canvas in the app.
 *
 * Four surfaces draw labels over a graph — the repo graph in 2D, its cluster
 * hulls, the estate service map, and the 3D scene — and each one had grown its
 * own copy of the same eight lines: keep a list of rectangles already taken,
 * test the next one against all of them, skip it if it collides. Five copies
 * in total, which is five chances for the rule to drift and no single place to
 * fix it when it does.
 *
 * The rule itself is not view-specific, so it lives here once. What IS
 * view-specific is which label deserves a contested spot — the repo graph
 * ranks by node type, the service map by whether a node is a gateway, the 3D
 * scene by whether a node is on the traced path. That is policy, it would
 * change independently in each view, and it deliberately stays there: this
 * module is handed an order and honours it.
 *
 * Coordinates are whatever space the caller draws in, screen pixels or graph
 * units. The rule is a comparison, so it does not care — but a single
 * LabelSpace must be fed one space consistently, or it is comparing
 * millimetres against miles.
 */

export interface LabelRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export function rectsOverlap(a: LabelRect, b: LabelRect): boolean {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

/**
 * The space labels have already taken on the frame being painted.
 *
 * For painters that decide as they draw, because a canvas render callback
 * gets one node at a time and cannot see the others. Reset it once per frame.
 */
export class LabelSpace {
  private bands = new Map<number, LabelRect[]>();
  private bandHeight = 0;

  /** Takes the rectangle if it is still clear, and reports whether it got it. */
  claim(rect: LabelRect): boolean {
    if (this.collides(rect)) return false;
    this.occupy(rect);
    return true;
  }

  /** Takes the rectangle whatever is under it — for a label that must appear. */
  reserve(rect: LabelRect): void {
    this.occupy(rect);
  }

  collides(rect: LabelRect): boolean {
    for (const band of this.bandsOf(rect)) {
      const taken = this.bands.get(band);
      if (taken?.some((other) => rectsOverlap(rect, other))) return true;
    }
    return false;
  }

  reset(): void {
    this.bands.clear();
    this.bandHeight = 0;
  }

  private occupy(rect: LabelRect): void {
    for (const band of this.bandsOf(rect)) {
      const taken = this.bands.get(band);
      if (taken) taken.push(rect);
      else this.bands.set(band, [rect]);
    }
  }

  /* Rows of roughly one label each, so a rectangle is compared against its
   * neighbours rather than against every label already placed. The height is
   * taken from the first rectangle seen, because labels on one canvas are a
   * uniform height and the caller should not have to say so.
   *
   * Band size is a speed knob and never a correctness one: a rectangle always
   * lists every band it touches, so a band too small merely means more of
   * them and a band too large merely means longer lists. */
  private bandsOf(rect: LabelRect): number[] {
    if (this.bandHeight <= 0) {
      this.bandHeight = Math.max(rect.bottom - rect.top, Number.MIN_VALUE);
    }
    const first = Math.floor(rect.top / this.bandHeight);
    const last = Math.floor(rect.bottom / this.bandHeight);
    const bands: number[] = [];
    for (let band = first; band <= last; band++) bands.push(band);
    return bands;
  }
}

export interface LabelBid {
  id: string;
  rect: LabelRect;
  /** Higher wins a contested rectangle. Ties break on id, so a settled map
   * does not flicker between two equally good answers. */
  priority: number;
  /** Drawn whatever it lands on, and still reserves its space so the labels
   * that yield to it do not also print through it. */
  pinned?: boolean;
}

/**
 * Which labels to draw, for callers that can decide before painting starts.
 *
 * Preferred over LabelSpace where the geometry is known up front, because the
 * answer for one label depends on all the others and settling that in one
 * place is easier to reason about than a paint loop with memory.
 */
export function placeLabels(bids: readonly LabelBid[]): Set<string> {
  const ordered = [...bids].sort((a, b) => {
    if (!!b.pinned !== !!a.pinned) return b.pinned ? 1 : -1;
    if (b.priority !== a.priority) return b.priority - a.priority;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  const space = new LabelSpace();
  const chosen = new Set<string>();
  for (const bid of ordered) {
    if (bid.pinned) {
      space.reserve(bid.rect);
      chosen.add(bid.id);
    } else if (space.claim(bid.rect)) {
      chosen.add(bid.id);
    }
  }
  return chosen;
}
