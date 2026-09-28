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

function repoQualifier(name: string): string {
  const slash = name.lastIndexOf("/");
  return slash === -1 ? "" : name.slice(0, slash);
}

/** The longest run of characters every one of these begins with. */
function sharedPrefix(values: readonly string[]): string {
  if (values.length === 0) return "";
  let prefix = values[0];
  for (const value of values.slice(1)) {
    let length = 0;
    while (length < prefix.length && length < value.length
           && prefix[length] === value[length]) length++;
    prefix = prefix.slice(0, length);
  }
  return prefix;
}

/**
 * Qualifiers reduced to the part that actually tells them apart.
 *
 * Keeping the whole qualifier is not enough on its own. Two repositories in
 * one organisation share almost all of their ids —
 * `spring-petclinic_spring-petclinic-cloud` against
 * `…-microservices` — so the only distinguishing characters sit in the middle,
 * which is exactly where `fitServiceLabel` cuts. The map drew three pairs of
 * identical names over six different services: the disambiguation was being
 * performed and then truncated away.
 *
 * Dropping what they all share leaves `cloud` and `microservices`, which fit
 * whole. The cut backs off to a separator so a token is never halved: two ids
 * sharing `abc` with no boundary in it keep their full qualifiers rather than
 * being served as `def` and `xyz`. Likewise if trimming would leave any of
 * them empty — a long label beats a blank one — or make two of them equal,
 * which dropping leading separators can: `org-x` and `org--x` both leave `x`.
 */
function distinguishingQualifiers(qualifiers: readonly string[]): Map<string, string> {
  const distinct = [...new Set(qualifiers)];
  const shared = sharedPrefix(distinct);
  const boundary = Math.max(
    shared.lastIndexOf("-"), shared.lastIndexOf("_"),
    shared.lastIndexOf("/"), shared.lastIndexOf("."),
  ) + 1;
  const trimmed = new Map<string, string>();
  for (const qualifier of distinct) {
    trimmed.set(qualifier, qualifier.slice(boundary).replace(/^[-_/.]+/, ""));
  }
  const values = [...trimmed.values()];
  if (values.some((value) => value.length === 0) || new Set(values).size < values.length) {
    return new Map(distinct.map((qualifier) => [qualifier, qualifier]));
  }
  return trimmed;
}

/**
 * Display name per node id. Ambiguity is never resolved by guessing: a bare
 * name shared by two drawn nodes keeps a qualifier on both, because two
 * identical labels on two different services is worse than a long one.
 */
export function serviceDisplayNames(
  nodes: readonly { id: string; name: string }[],
): Map<string, string> {
  const byBareName = new Map<string, string[]>();
  for (const node of nodes) {
    const bare = bareServiceName(node.name);
    byBareName.set(bare, [...(byBareName.get(bare) ?? []), repoQualifier(node.name)]);
  }
  const names = new Map<string, string>();
  for (const node of nodes) {
    const bare = bareServiceName(node.name);
    const sharing = byBareName.get(bare) ?? [];
    if (sharing.length === 1) {
      names.set(node.id, bare);
      continue;
    }
    const qualifier = repoQualifier(node.name);
    const shown = distinguishingQualifiers(sharing).get(qualifier) ?? qualifier;
    names.set(node.id, shown ? `${shown}/${bare}` : bare);
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
