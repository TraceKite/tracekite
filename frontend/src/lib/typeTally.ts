/** The node or edge types a filter panel lists, with how many of each.
 *
 * Listed from the view's own data, never from a fixed vocabulary. A fixed list
 * showed IMPORTS, IMPLEMENTS, CALLS_API and nine more at 0 on every repository:
 * the backend never writes them, so each 0 read as a measured absence — "this
 * repository has no imports" — when the graph simply does not model them.
 */

export interface TypeTally {
  type: string;
  count: number;
}

/** Every type present, plus every hidden one so it can always be shown again. */
export function tallyTypes(
  items: readonly { type: string }[],
  hidden: readonly string[],
): TypeTally[] {
  const counts = new Map<string, number>(hidden.map((type) => [type, 0]));
  for (const item of items) counts.set(item.type, (counts.get(item.type) ?? 0) + 1);
  return [...counts]
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count || a.type.localeCompare(b.type));
}
