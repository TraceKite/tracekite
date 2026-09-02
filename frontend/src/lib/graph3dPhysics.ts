import type { GraphNode, GraphLink } from "@/lib/types";
import { graphGroupOf } from "@/lib/graphStyle";
import { endpointId } from "@/lib/graphVisibility";
import { stableJitter } from "@/lib/graphStablePosition";

export interface Node3DPhysicsState {
  i: number;
  id: string;
  node: GraphNode;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  sx: number;
  sy: number;
  sz: number;
  sr: number;
  size: number;
  alpha: number;
  scale: number;
  vis: boolean;
  degree: number;
  depth: number;
}

export type Layout3DMode = "atlas" | "sphere" | "layers";

export interface LayoutAnchors {
  atlas: [number, number, number][];
  sphere: [number, number, number][];
  layers: [number, number, number][];
}

const TIER_MAP: Record<string, number> = {
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
 * Initialize 3D physics states for graph nodes positioned directly near anchors.
 */
export function initPhysicsNodes(
  nodes: GraphNode[],
  anchors: [number, number, number][] = [],
  links: GraphLink[] = [],
): Node3DPhysicsState[] {
  const degrees = new Map<string, number>();
  for (const link of links) {
    const source = endpointId(link.source);
    const target = endpointId(link.target);
    degrees.set(source, (degrees.get(source) ?? 0) + 1);
    degrees.set(target, (degrees.get(target) ?? 0) + 1);
  }
  return nodes.map((node, i) => {
    const anchor = anchors[i] || [0, 0, 0];
    return {
      i,
      id: node.id,
      node,
      x: anchor[0] + stableJitter(node.id, 0),
      y: anchor[1] + stableJitter(node.id, 1),
      z: anchor[2] + stableJitter(node.id, 2),
      vx: 0,
      vy: 0,
      vz: 0,
      sx: 0,
      sy: 0,
      sz: 0,
      sr: 8,
      size: 1.0 + Math.min(node.size || 4, 12) * 0.25,
      alpha: 1.0,
      scale: 1.0,
      vis: true,
      degree: degrees.get(node.id) ?? 0,
      depth: TIER_MAP[node.type] ?? 2,
    };
  });
}

/**
 * Compute layout anchors matching reference physics scale (~42 unit radius).
 */
export function computeLayoutAnchors(
  nodes: GraphNode[],
  links: GraphLink[],
  radius: number = 42
): LayoutAnchors {
  const n = nodes.length;
  const anchors: LayoutAnchors = { atlas: [], sphere: [], layers: [] };
  if (n === 0) return anchors;

  const clusterMap = new Map<string, number[]>();
  nodes.forEach((node, i) => {
    const mod = graphGroupOf(node);
    if (!clusterMap.has(mod)) clusterMap.set(mod, []);
    clusterMap.get(mod)!.push(i);
  });

  const clusters = Array.from(clusterMap.keys());
  const numClusters = Math.max(1, clusters.length);

  const clusterDirs = new Map<string, [number, number, number]>();
  clusters.forEach((cid, idx) => {
    const theta = (idx / numClusters) * Math.PI * 2;
    const phi = ((idx % 3) - 1) * 0.42;
    const x = Math.cos(theta) * Math.cos(phi);
    const y = Math.sin(phi) * 0.85;
    const z = Math.sin(theta) * Math.cos(phi);
    const len = Math.hypot(x, y, z) || 1;
    clusterDirs.set(cid, [x / len, y / len, z / len]);
  });

  const goldenAngle = Math.PI * (3 - Math.sqrt(5));

  nodes.forEach((node, i) => {
    const mod = graphGroupOf(node);
    const dir = clusterDirs.get(mod) || [0, 0, 0];
    const cNodes = clusterMap.get(mod) || [i];
    const cIdx = cNodes.indexOf(i);
    const cTotal = cNodes.length;

    // --- Atlas Layout (Clustered) ---
    const spread = (cIdx / Math.max(1, cTotal)) * Math.PI * 2;
    const localR = Math.pow(cTotal, 0.4) * 6.5;
    const ax = dir[0] * radius * 0.85 + Math.cos(spread) * localR;
    const ay = dir[1] * radius * 0.85 + ((cIdx % 3) - 1) * (localR * 0.5);
    const az = dir[2] * radius * 0.85 + Math.sin(spread) * localR;
    anchors.atlas.push([ax, ay, az]);

    // --- Sphere / Shell Layout (Fibonacci distribution) ---
    const y = n === 1 ? 0 : 1 - (i / Math.max(1, n - 1)) * 2;
    const rAtY = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = goldenAngle * i;
    const sx = Math.cos(theta) * rAtY * radius;
    const sy = y * radius;
    const sz = Math.sin(theta) * rAtY * radius;
    anchors.sphere.push([sx, sy, sz]);

    // --- Layers / Tier Layout (Elevation tiers) ---
    const tier = TIER_MAP[node.type] ?? 2;
    const layerY = (2 - tier) * 16;
    const lx = dir[0] * (radius * 0.72) + Math.cos(spread) * (localR * 0.8);
    const lz = dir[2] * (radius * 0.72) + Math.sin(spread) * (localR * 0.8);
    anchors.layers.push([lx, layerY, lz]);
  });

  return anchors;
}

/**
 * Step 3D N-body physics simulation using clamped, unconditionally stable forces.
 */
export function stepPhysicsSimulation(
  nodes: Node3DPhysicsState[],
  links: GraphLink[],
  nodeIndexMap: Map<string, number>,
  anchors: [number, number, number][],
  alpha: number
) {
  if (alpha < 0.003 || nodes.length === 0 || anchors.length === 0) return;

  const n = nodes.length;
  const MAX_VELOCITY = 3.0;
  const SPRING_DIST = 8;
  const SPRING_K = 0.02;
  const ANCHOR_K = 0.08;
  const DAMPING = 0.85;

  // 1. Edge Springs
  for (let i = 0; i < links.length; i++) {
    const link = links[i];
    const srcId = typeof link.source === "object" ? (link.source as any).id : link.source;
    const tgtId = typeof link.target === "object" ? (link.target as any).id : link.target;
    const sIdx = nodeIndexMap.get(srcId);
    const tIdx = nodeIndexMap.get(tgtId);

    if (sIdx !== undefined && tIdx !== undefined) {
      const s = nodes[sIdx];
      const t = nodes[tIdx];

      let dx = t.x - s.x;
      let dy = t.y - s.y;
      let dz = t.z - s.z;
      const dist = Math.hypot(dx, dy, dz) || 1;
      const force = Math.max(-1.0, Math.min(1.0, (dist - SPRING_DIST) * SPRING_K));

      dx /= dist;
      dy /= dist;
      dz /= dist;

      s.vx += dx * force;
      s.vy += dy * force;
      s.vz += dz * force;

      t.vx -= dx * force;
      t.vy -= dy * force;
      t.vz -= dz * force;
    }
  }

  // 2. Anchor Pull + Clamping + Integration
  for (let i = 0; i < n; i++) {
    const ni = nodes[i];
    const target = anchors[i];
    if (target) {
      ni.vx += (target[0] - ni.x) * ANCHOR_K;
      ni.vy += (target[1] - ni.y) * ANCHOR_K;
      ni.vz += (target[2] - ni.z) * ANCHOR_K;
    }

    ni.vx = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, ni.vx * DAMPING));
    ni.vy = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, ni.vy * DAMPING));
    ni.vz = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, ni.vz * DAMPING));

    ni.x += ni.vx * alpha;
    ni.y += ni.vy * alpha;
    ni.z += ni.vz * alpha;
  }
}
