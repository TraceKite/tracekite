import type { GraphLink, GraphNode, ViewMode } from "./types.ts";
import { graphGroupOf } from "./graphStyle.ts";
import { endpointId } from "./graphVisibility.ts";

export interface GraphProjection {
  nodes: GraphNode[];
  links: GraphLink[];
  totalNodeCount?: number;
}

export function usesGroupedEntry(viewMode: ViewMode): boolean {
  return viewMode !== "impact";
}

export function isModuleGroup(node: GraphNode): boolean {
  return node.type === "ModuleGroup" && node.metadata.aggregate === true;
}

export function moduleGroupKey(node: GraphNode): string | null {
  return isModuleGroup(node) ? String(node.metadata.group_key ?? "") || null : null;
}

export function buildModuleOverview(
  nodes: GraphNode[],
  links: GraphLink[],
): GraphProjection {
  const groups = new Map<string, GraphNode[]>();
  const groupByNodeId = new Map<string, string>();
  for (const node of nodes) {
    const key = graphGroupOf(node);
    const members = groups.get(key) ?? [];
    members.push(node);
    groups.set(key, members);
    groupByNodeId.set(node.id, key);
  }
  const internalEdges = new Map<string, number>();
  const corridors = new Map<string, {
    source: string;
    target: string;
    count: number;
    types: Set<string>;
    confidence: number | null;
  }>();
  for (const link of links) {
    const sourceGroup = groupByNodeId.get(endpointId(link.source));
    const targetGroup = groupByNodeId.get(endpointId(link.target));
    if (!sourceGroup || !targetGroup) continue;
    if (sourceGroup === targetGroup) {
      internalEdges.set(sourceGroup, (internalEdges.get(sourceGroup) ?? 0) + 1);
      continue;
    }
    const key = `${sourceGroup}->${targetGroup}`;
    const corridor = corridors.get(key) ?? {
      source: sourceGroup,
      target: targetGroup,
      count: 0,
      types: new Set<string>(),
      confidence: null,
    };
    corridor.count += 1;
    corridor.types.add(link.type);
    if (link.confidence != null) {
      corridor.confidence = corridor.confidence == null
        ? link.confidence
        : Math.min(corridor.confidence, link.confidence);
    }
    corridors.set(key, corridor);
  }
  const orderedGroups = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  const keysByRepo = new Map<string, string[]>();
  for (const [key] of orderedGroups) {
    const repoKey = key.split("/").slice(0, 2).join("/") || "unscoped";
    keysByRepo.set(repoKey, [...(keysByRepo.get(repoKey) ?? []), key]);
  }
  const repoKeys = [...keysByRepo.keys()].sort();
  const positionByGroup = new Map<string, { x: number; y: number }>();
  repoKeys.forEach((repoKey, repoIndex) => {
    const repoAngle = repoKeys.length === 1 ? 0 : (repoIndex / repoKeys.length) * Math.PI * 2;
    const centerX = repoKeys.length === 1 ? 0 : Math.cos(repoAngle) * 180;
    const centerY = repoKeys.length === 1 ? 0 : Math.sin(repoAngle) * 120;
    const keys = (keysByRepo.get(repoKey) ?? []).sort();
    const root = keys.find((key) => key.endsWith("/Repo"));
    if (root) positionByGroup.set(root, { x: centerX, y: centerY });
    const satellites = keys.filter((key) => key !== root);
    satellites.forEach((key, index) => {
      const angle = (index / Math.max(1, satellites.length)) * Math.PI * 2 - Math.PI / 2;
      const radius = Math.max(82, Math.min(118, 72 + satellites.length * 5));
      positionByGroup.set(key, {
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
      });
    });
  });
  const overviewNodes = orderedGroups
    .map(([key, members]) => {
      const nodeTypes: Record<string, number> = {};
      for (const member of members) {
        nodeTypes[member.type] = (nodeTypes[member.type] ?? 0) + 1;
      }
      const position = positionByGroup.get(key) ?? { x: 0, y: 0 };
      return {
        id: `module-group:${key}`,
        type: "ModuleGroup",
        label: `${key} · ${members.length}`,
        name: key,
        size: Math.min(30, 10 + Math.sqrt(members.length) * 2),
        group: key,
        x: position.x,
        y: position.y,
        fx: position.x,
        fy: position.y,
        metadata: {
          aggregate: true,
          group_key: key,
          member_count: members.length,
          internal_edge_count: internalEdges.get(key) ?? 0,
          node_types: nodeTypes,
        },
      } satisfies GraphNode;
    });
  const overviewLinks = [...corridors.values()].map((corridor) => {
    const relationshipTypes = [...corridor.types].sort();
    return {
      id: `module-corridor:${corridor.source}->${corridor.target}`,
      source: `module-group:${corridor.source}`,
      target: `module-group:${corridor.target}`,
      type: relationshipTypes.length === 1 ? relationshipTypes[0] : "AGGREGATE",
      label: `${corridor.count} verified relationships`,
      value: corridor.count,
      confidence: corridor.confidence,
      aggregate: true,
      member_count: corridor.count,
      relationship_types: relationshipTypes,
    } satisfies GraphLink;
  });
  return { nodes: overviewNodes, links: overviewLinks };
}

export function buildGroupDetail(
  nodes: GraphNode[],
  links: GraphLink[],
  groupKey: string,
  nodeLimit = 80,
): GraphProjection {
  const allMembers = nodes.filter((node) => graphGroupOf(node) === groupKey);
  const allIds = new Set(allMembers.map((node) => node.id));
  const degree = new Map<string, number>();
  for (const link of links) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    if (!allIds.has(source) || !allIds.has(target)) continue;
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
  }
  const members = [...allMembers]
    .sort((left, right) =>
      (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0) ||
      (right.size ?? 0) - (left.size ?? 0) ||
      left.id.localeCompare(right.id))
    .slice(0, Math.max(1, nodeLimit));
  const ids = new Set(members.map((node) => node.id));
  return {
    nodes: members,
    links: links.filter((link) =>
      ids.has(endpointId(link.source)) && ids.has(endpointId(link.target))),
    totalNodeCount: allMembers.length,
  };
}

export function buildOneHopNeighborhood(
  nodes: GraphNode[],
  links: GraphLink[],
  focusId: string,
  nodeLimit = 80,
): GraphProjection {
  const neighborIds = new Set<string>();
  const incident = links.filter((link) => {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    const matches = source === focusId || target === focusId;
    if (matches) {
      if (source !== focusId) neighborIds.add(source);
      if (target !== focusId) neighborIds.add(target);
    }
    return matches;
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const selectedNeighbors = [...neighborIds]
    .map((id) => byId.get(id))
    .filter((node): node is GraphNode => Boolean(node))
    .sort((left, right) =>
      (right.size ?? 0) - (left.size ?? 0) || left.id.localeCompare(right.id))
    .slice(0, Math.max(0, nodeLimit - 1));
  const ids = new Set([focusId, ...selectedNeighbors.map((node) => node.id)]);
  return {
    nodes: nodes.filter((node) => ids.has(node.id)),
    links: incident.filter((link) =>
      ids.has(endpointId(link.source)) && ids.has(endpointId(link.target))),
    totalNodeCount: neighborIds.size + 1,
  };
}

export function buildBoundedImpact(
  nodes: GraphNode[],
  links: GraphLink[],
  focusId: string,
  nodeLimit = 80,
): GraphProjection {
  const adjacency = new Map<string, Set<string>>();
  for (const link of links) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    const sourceNeighbors = adjacency.get(source) ?? new Set<string>();
    const targetNeighbors = adjacency.get(target) ?? new Set<string>();
    sourceNeighbors.add(target);
    targetNeighbors.add(source);
    adjacency.set(source, sourceNeighbors);
    adjacency.set(target, targetNeighbors);
  }
  const distance = new Map<string, number>([[focusId, 0]]);
  const queue = [focusId];
  for (let index = 0; index < queue.length; index += 1) {
    const current = queue[index];
    for (const neighbor of adjacency.get(current) ?? []) {
      if (distance.has(neighbor)) continue;
      distance.set(neighbor, (distance.get(current) ?? 0) + 1);
      queue.push(neighbor);
    }
  }
  const selected = [...nodes]
    .sort((left, right) =>
      (left.id === focusId ? -1 : right.id === focusId ? 1 : 0) ||
      (distance.get(left.id) ?? Infinity) - (distance.get(right.id) ?? Infinity) ||
      (right.size ?? 0) - (left.size ?? 0) || left.id.localeCompare(right.id))
    .slice(0, Math.max(1, nodeLimit));
  const ids = new Set(selected.map((node) => node.id));
  return {
    nodes: selected,
    links: links.filter((link) =>
      ids.has(endpointId(link.source)) && ids.has(endpointId(link.target))),
    totalNodeCount: nodes.length,
  };
}
