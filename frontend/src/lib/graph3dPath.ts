import type { GraphLink } from "./types.ts";

/**
 * Find a directed path through edges already present on the sampled canvas.
 * This is not the ranked, evidence-bearing service Trace contract.
 */
export function findDirectedPath(
  sourceId: string,
  targetId: string,
  links: GraphLink[]
): string[] | null {
  if (sourceId === targetId) return [sourceId];

  const adj = new Map<string, string[]>();

  links.forEach((link) => {
    const s = typeof link.source === "object" ? (link.source as any).id : link.source;
    const t = typeof link.target === "object" ? (link.target as any).id : link.target;

    if (!adj.has(s)) adj.set(s, []);
    adj.get(s)!.push(t);
  });

  const queue: string[] = [sourceId];
  let cursor = 0;
  const visited = new Set<string>([sourceId]);
  const parent = new Map<string, string>();

  while (cursor < queue.length) {
    const curr = queue[cursor++];
    if (curr === targetId) {
      const path: string[] = [];
      let step: string | undefined = targetId;
      while (step) {
        path.unshift(step);
        step = parent.get(step);
      }
      return path;
    }

    const neighbors = adj.get(curr) || [];
    for (const next of neighbors) {
      if (!visited.has(next)) {
        visited.add(next);
        parent.set(next, curr);
        queue.push(next);
      }
    }
  }

  return null;
}

/**
 * Get 1-hop neighbors of a node.
 */
export function getNeighbors(
  nodeId: string,
  links: GraphLink[]
): Set<string> {
  const neighbors = new Set<string>([nodeId]);

  links.forEach((link) => {
    const s = typeof link.source === "object" ? (link.source as any).id : link.source;
    const t = typeof link.target === "object" ? (link.target as any).id : link.target;

    if (s === nodeId) neighbors.add(t);
    if (t === nodeId) neighbors.add(s);
  });

  return neighbors;
}

/**
 * Determine if an edge is part of the active path.
 */
export function isEdgeInPath(
  link: GraphLink,
  path: string[]
): boolean {
  const s = typeof link.source === "object" ? (link.source as any).id : link.source;
  const t = typeof link.target === "object" ? (link.target as any).id : link.target;

  for (let i = 0; i < path.length - 1; i++) {
    if (path[i] === s && path[i + 1] === t) {
      return true;
    }
  }
  return false;
}
