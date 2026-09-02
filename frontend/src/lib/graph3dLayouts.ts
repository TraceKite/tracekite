import type { GraphNode, GraphLink } from "@/lib/types";
import { moduleOf } from "@/lib/graphStyle";

export type Layout3DMode = "atlas" | "sphere" | "layers";

export interface Node3DPosition {
  x: number;
  y: number;
  z: number;
}

const TIER_ORDER: Record<string, number> = {
  ApiEndpoint: 0,
  ExternalApi: 0,
  DockerResource: 0,
  KubernetesResource: 0,
  Repo: 1,
  Package: 1,
  Folder: 1,
  File: 2,
  Class: 2,
  Interface: 2,
  component: 3,
  Function: 3,
  Method: 3,
  Dependency: 4,
  Config: 4,
  ExternalSystem: 4,
  Test: 4,
};

/**
 * Compute Sphere layout: Fibonacci distribution along a 3D celestial shell.
 */
export function computeSphereLayout(
  nodes: GraphNode[]
): Map<string, Node3DPosition> {
  const positions = new Map<string, Node3DPosition>();
  const n = nodes.length;
  if (n === 0) return positions;

  // Scale radius with node density for comfortable spacing
  const radius = Math.max(160, Math.min(280, Math.sqrt(n) * 32));

  // Sort nodes by module/group so connected services sit close together on the sphere
  const sortedNodes = [...nodes].sort((a, b) => {
    const modA = (a.path ? moduleOf(a.path) : "") || a.group || a.type;
    const modB = (b.path ? moduleOf(b.path) : "") || b.group || b.type;
    return modA.localeCompare(modB);
  });

  const phi = Math.PI * (3 - Math.sqrt(5)); // Golden spiral angle

  sortedNodes.forEach((node, i) => {
    const y = n === 1 ? 0 : 1 - (i / (n - 1)) * 2; // +1 (north pole) to -1 (south pole)
    const rAtY = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = phi * i;

    const x = Math.cos(theta) * rAtY * radius;
    const z = Math.sin(theta) * rAtY * radius;
    positions.set(node.id, { x, y: y * radius, z });
  });

  return positions;
}

/**
 * Compute Tier/Layers layout: Vertical architectural elevation layers.
 */
export function computeTierLayout(
  nodes: GraphNode[],
  layerSpacing: number = 100
): Map<string, Node3DPosition> {
  const positions = new Map<string, Node3DPosition>();
  const tiers: Map<number, GraphNode[]> = new Map();

  nodes.forEach((node) => {
    const tier = TIER_ORDER[node.type] ?? 2;
    if (!tiers.has(tier)) tiers.set(tier, []);
    tiers.get(tier)!.push(node);
  });

  tiers.forEach((tierNodes, tierIdx) => {
    // Top tier at positive Y, lower tiers at negative Y
    const y = (2 - tierIdx) * layerSpacing;
    const count = tierNodes.length;
    const radius = Math.max(40, Math.sqrt(count) * 28);

    tierNodes.forEach((node, idx) => {
      const angle = (idx / count) * Math.PI * 2;
      const x = Math.cos(angle) * radius;
      const z = Math.sin(angle) * radius;
      positions.set(node.id, { x, y, z });
    });
  });

  return positions;
}

/**
 * Compute Atlas layout: 3D Clustered spatial arrangement.
 */
export function computeAtlasLayout(
  nodes: GraphNode[],
  links: GraphLink[],
  spread: number = 240
): Map<string, Node3DPosition> {
  const positions = new Map<string, Node3DPosition>();
  const clusters = new Map<string, GraphNode[]>();

  nodes.forEach((node) => {
    const cid = (node.path ? moduleOf(node.path) : "") || node.group || node.type || "default";
    if (!clusters.has(cid)) clusters.set(cid, []);
    clusters.get(cid)!.push(node);
  });

  const clusterKeys = Array.from(clusters.keys());
  const numClusters = clusterKeys.length;
  const clusterCenters = new Map<string, Node3DPosition>();

  // Place cluster centers on a 3D sphere ring
  clusterKeys.forEach((cid, i) => {
    const theta = (i / numClusters) * Math.PI * 2;
    const phi = ((i % 3) - 1) * 0.45;
    const cx = Math.cos(theta) * Math.cos(phi) * spread;
    const cy = Math.sin(phi) * spread * 0.7;
    const cz = Math.sin(theta) * Math.cos(phi) * spread;
    clusterCenters.set(cid, { x: cx, y: cy, z: cz });
  });

  // Position nodes inside their cluster volume
  clusterKeys.forEach((cid) => {
    const cNodes = clusters.get(cid)!;
    const center = clusterCenters.get(cid)!;
    const cCount = cNodes.length;
    const cRadius = Math.max(25, Math.pow(cCount, 1 / 3) * 32);

    cNodes.forEach((node, idx) => {
      const u = idx / Math.max(1, cCount);
      const theta = u * Math.PI * 2 * 3.14;
      const phi = (idx % 5) * 0.6 - 1.2;
      const r = (0.2 + 0.8 * Math.sqrt((idx + 1) / cCount)) * cRadius;

      const x = center.x + Math.cos(theta) * Math.cos(phi) * r;
      const y = center.y + Math.sin(phi) * r;
      const z = center.z + Math.sin(theta) * Math.cos(phi) * r;
      positions.set(node.id, { x, y, z });
    });
  });

  return positions;
}

export function compute3DPositions(
  mode: Layout3DMode,
  nodes: GraphNode[],
  links: GraphLink[]
): Map<string, Node3DPosition> {
  switch (mode) {
    case "sphere":
      return computeSphereLayout(nodes);
    case "layers":
      return computeTierLayout(nodes);
    case "atlas":
    default:
      return computeAtlasLayout(nodes, links);
  }
}
