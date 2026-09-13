/**
 * What a service node is called on the canvas.
 *
 * Service names arrive repo-qualified — `owner_repo/config-server` — which is
 * 376px at the paint font and wider than the slot any layout can give it. The
 * qualifier is also redundant with the scope control most of the time, so it
 * is dropped where the bare name still names exactly one node, and only kept
 * where two repos really do contribute the same service name.
 */

const ELLIPSIS = "…";

/** Wider than this and a label stops being a label and becomes a banner. */
export const MAX_SERVICE_LABEL_PX = 180;

export function bareServiceName(name: string): string {
  const slash = name.lastIndexOf("/");
  return slash === -1 ? name : name.slice(slash + 1);
}

/**
 * Display name per node id. Ambiguity is never resolved by guessing: a bare
 * name shared by two drawn nodes keeps its qualifier on both, because two
 * identical labels on two different services is worse than a long one.
 */
export function serviceDisplayNames(
  nodes: readonly { id: string; name: string }[],
): Map<string, string> {
  const seen = new Map<string, number>();
  for (const node of nodes) {
    const bare = bareServiceName(node.name);
    seen.set(bare, (seen.get(bare) ?? 0) + 1);
  }
  const names = new Map<string, string>();
  for (const node of nodes) {
    const bare = bareServiceName(node.name);
    names.set(node.id, seen.get(bare) === 1 ? bare : node.name);
  }
  return names;
}

/**
 * Shorten to fit `budgetPx`, cutting from the middle.
 *
 * Both ends carry identity — the tail is the service, the head is which repo
 * it came from — so the expendable part is the path between them. `measure`
 * returns screen pixels, which is what the budget is in: labels paint at a
 * constant on-screen size, so graph units would be meaningless here.
 */
export function fitServiceLabel(
  label: string,
  budgetPx: number,
  measure: (text: string) => number,
): string {
  if (budgetPx <= 0) return label;
  if (measure(label) <= budgetPx) return label;

  const build = (keep: number) => {
    const head = Math.ceil(keep / 2);
    return label.slice(0, head) + ELLIPSIS + label.slice(label.length - (keep - head));
  };
  // Binary search rather than a walk: this runs per node per frame, and a
  // linear scan over a 60-character name is 60 text measurements a frame.
  let low = 1;
  let high = label.length - 1;
  let best = ELLIPSIS;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const candidate = build(mid);
    if (measure(candidate) <= budgetPx) {
      best = candidate;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return best;
}
