import type { GraphLink, GraphNode } from "./types.ts";
import { endpointId } from "./graphVisibility.ts";

export interface GraphFocusContext {
  nodeIds: Set<string>;
  linkIds: Set<string>;
}

export interface GraphLabelBudget {
  overview: Set<string>;
  medium: Set<string>;
  detail: Set<string>;
}

export function graphLinkId(link: GraphLink): string {
  return link.id ?? `${endpointId(link.source)}->${endpointId(link.target)}->${link.type}`;
}

export function computeFocusContext(
  links: GraphLink[],
  focusId: string | null,
): GraphFocusContext {
  if (!focusId) return { nodeIds: new Set(), linkIds: new Set() };
  const nodeIds = new Set<string>([focusId]);
  const linkIds = new Set<string>();
  for (const link of links) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    if (source !== focusId && target !== focusId) continue;
    nodeIds.add(source);
    nodeIds.add(target);
    linkIds.add(graphLinkId(link));
  }
  return { nodeIds, linkIds };
}

export function buildNodeIndex(nodes: GraphNode[]): Map<string, GraphNode> {
  return new Map(nodes.map((node) => [node.id, node]));
}

export function buildLabelBudget(
  nodes: GraphNode[],
  links: GraphLink[],
  focusId: string | null,
): GraphLabelBudget {
  const degree = new Map<string, number>();
  for (const link of links) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
  }
  const focus = computeFocusContext(links, focusId).nodeIds;
  const typeScore: Record<string, number> = {
    Repo: 20_000,
    Folder: 12_000,
    Package: 11_000,
    ApiEndpoint: 8_000,
    ContractOperation: 8_000,
    HttpContract: 8_000,
    Topic: 7_000,
    File: 3_000,
  };
  const ranked = [...nodes].sort((a, b) => {
    const score = (node: GraphNode) =>
      (node.id === focusId ? 100_000 : focus.has(node.id) ? 50_000 : 0) +
      (typeScore[node.type] ?? 0) +
      (degree.get(node.id) ?? 0) * 120 +
      Math.min(node.size ?? 0, 20);
    return score(b) - score(a) || a.id.localeCompare(b.id);
  });
  const root = Math.sqrt(nodes.length);
  const overviewCount = Math.min(24, Math.max(10, Math.ceil(root)));
  const mediumCount = Math.min(48, Math.max(24, Math.ceil(root * 2)));
  const detailCount = Math.min(96, Math.max(48, Math.ceil(root * 4)));
  const take = (count: number) => new Set(ranked.slice(0, count).map((node) => node.id));
  return {
    overview: take(overviewCount),
    medium: take(mediumCount),
    detail: take(detailCount),
  };
}

export function labelIdsForScale(
  budget: GraphLabelBudget,
  globalScale: number,
  focused: boolean,
): Set<string> {
  if (focused) return globalScale >= 1.7 ? budget.medium : budget.overview;
  if (globalScale >= 0.9) return globalScale >= 1.7 ? budget.detail : budget.medium;
  return budget.overview;
}
