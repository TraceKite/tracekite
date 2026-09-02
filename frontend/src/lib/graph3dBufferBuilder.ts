import * as THREE from "three";
import type { GraphLink } from "@/lib/types";
import {
  getNodeColor,
  getEdgeColor,
  isCrossingEdge,
  graphGroupOf,
  getModuleColor,
} from "@/lib/graphStyle";
import { getNeighbors, isEdgeInPath } from "@/lib/graph3dPath";
import { isNodeVisible } from "@/lib/graphVisibility";
import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

/**
 * Initialize GPU geometry buffers for Nodes.
 */
export function initNodeBuffers(nodeGeo: THREE.BufferGeometry, n: number) {
  nodeGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  nodeGeo.setAttribute("aColor", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  nodeGeo.setAttribute("aSize", new THREE.BufferAttribute(new Float32Array(n), 1));
  nodeGeo.setAttribute("aAlpha", new THREE.BufferAttribute(new Float32Array(n), 1));
  nodeGeo.setAttribute("aScale", new THREE.BufferAttribute(new Float32Array(n), 1));
}

/**
 * Initialize GPU geometry buffers for Edges.
 */
export function initEdgeBuffers(edgeGeo: THREE.BufferGeometry, linkCount: number) {
  edgeGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(linkCount * 6), 3));
  edgeGeo.setAttribute("aColor", new THREE.BufferAttribute(new Float32Array(linkCount * 6), 3));
  edgeGeo.setAttribute("aT", new THREE.BufferAttribute(new Float32Array(linkCount * 2), 1));
  edgeGeo.setAttribute("aSeed", new THREE.BufferAttribute(new Float32Array(linkCount * 2), 1));
  edgeGeo.setAttribute("aAlpha", new THREE.BufferAttribute(new Float32Array(linkCount * 2), 1));
  edgeGeo.setAttribute("aDir", new THREE.BufferAttribute(new Float32Array(linkCount * 2), 1));
}

/**
 * Sync dynamic physics positions, filter states, and visual highlights to GPU Buffers.
 */
export function syncBuffersToGPU(
  nodeGeo: THREE.BufferGeometry,
  edgeGeo: THREE.BufferGeometry,
  nodes: Node3DPhysicsState[],
  links: GraphLink[],
  nodeIndexMap: Map<string, number>,
  selectedNodeId: string | null,
  hoverNodeId: string | null,
  activePath3d: string[] | null,
  filteredNodeTypes: string[],
  filteredEdgeTypes: string[],
  searchQuery: string,
  hideLockfileDeps: boolean = false,
  connectionsOnly: boolean = false,
  highlightedEdgeTypes: string[] = [],
) {
  const posAttr = nodeGeo.getAttribute("position") as THREE.BufferAttribute;
  const colAttr = nodeGeo.getAttribute("aColor") as THREE.BufferAttribute;
  const sizeAttr = nodeGeo.getAttribute("aSize") as THREE.BufferAttribute;
  const alpAttr = nodeGeo.getAttribute("aAlpha") as THREE.BufferAttribute;
  const scaAttr = nodeGeo.getAttribute("aScale") as THREE.BufferAttribute;

  if (!posAttr || posAttr.count !== nodes.length) return;

  const moduleOrder = [
    ...new Set(
      nodes
        .map((n) => graphGroupOf(n.node))
        .filter(Boolean)
    ),
  ].sort();

  const activeFocusId = selectedNodeId || hoverNodeId;
  const neighborSet = activeFocusId ? getNeighbors(activeFocusId, links) : null;
  const pathSet = activePath3d ? new Set(activePath3d) : null;
  const q = searchQuery.trim().toLowerCase();
  const crossingNodeIds = new Set<string>();
  const highlightedNodeIds = new Set<string>();
  for (const link of links) {
    const source = typeof link.source === "object" ? (link.source as any).id : link.source;
    const target = typeof link.target === "object" ? (link.target as any).id : link.target;
    if (link.type === "INVOKES" || link.type === "EXPOSES") {
      crossingNodeIds.add(source);
      crossingNodeIds.add(target);
    }
    if (highlightedEdgeTypes.includes(link.type)) {
      highlightedNodeIds.add(source);
      highlightedNodeIds.add(target);
    }
  }

  nodes.forEach((n, i) => {
    posAttr.setXYZ(i, n.x, n.y, n.z);

    const mod = graphGroupOf(n.node);
    const modHex = getModuleColor(mod, moduleOrder) || getNodeColor(n.node.type);
    const c = new THREE.Color(modHex);
    colAttr.setXYZ(i, c.r, c.g, c.b);

    const isHub = n.node.type === "ModuleGroup" || n.node.type === "Folder" ||
      n.node.type === "Repo" || n.node.type === "Package";
    const isEndpoint = n.node.type === "ApiEndpoint";
    const baseSize = isHub ? 2.25 : isEndpoint ? 1.45 : 1.05;
    sizeAttr.setX(i, baseSize + Math.min(n.node.size || 2, 6) * 0.1);

    const isTypeAllowed = isNodeVisible(n.node, filteredNodeTypes, hideLockfileDeps);
    const isSearchMatch = !q || n.node.label.toLowerCase().includes(q) || n.node.name.toLowerCase().includes(q);

    n.vis = isTypeAllowed && (!connectionsOnly || crossingNodeIds.has(n.id));

    let alpha = n.vis ? 1.0 : 0.0;
    let scale = n.vis ? 1.0 : 0.0;

    if (n.vis) {
      if (pathSet) {
        alpha = pathSet.has(n.id) ? 1.0 : 0.12;
        scale = pathSet.has(n.id) ? 1.6 : 0.65;
      } else if (neighborSet) {
        alpha = neighborSet.has(n.id) ? 1.0 : 0.18;
        scale = n.id === activeFocusId ? 1.8 : neighborSet.has(n.id) ? 1.3 : 0.70;
      } else if (q) {
        alpha = isSearchMatch ? 1.0 : 0.12;
        scale = isSearchMatch ? 1.45 : 0.7;
      }
      if (highlightedEdgeTypes.length && !highlightedNodeIds.has(n.id)) {
        alpha *= 0.12;
        scale *= 0.8;
      }
    }

    n.alpha = alpha;
    n.scale = scale;
    alpAttr.setX(i, alpha);
    scaAttr.setX(i, scale);
  });

  posAttr.needsUpdate = true;
  colAttr.needsUpdate = true;
  sizeAttr.needsUpdate = true;
  alpAttr.needsUpdate = true;
  scaAttr.needsUpdate = true;

  // Sync Edges
  const ePosAttr = edgeGeo.getAttribute("position") as THREE.BufferAttribute;
  const eColAttr = edgeGeo.getAttribute("aColor") as THREE.BufferAttribute;
  const eTAttr = edgeGeo.getAttribute("aT") as THREE.BufferAttribute;
  const eSeedAttr = edgeGeo.getAttribute("aSeed") as THREE.BufferAttribute;
  const eAlpAttr = edgeGeo.getAttribute("aAlpha") as THREE.BufferAttribute;
  const eDirAttr = edgeGeo.getAttribute("aDir") as THREE.BufferAttribute;

  if (!ePosAttr || ePosAttr.count !== links.length * 2) return;

  links.forEach((link, i) => {
    const srcId = typeof link.source === "object" ? (link.source as any).id : link.source;
    const tgtId = typeof link.target === "object" ? (link.target as any).id : link.target;
    const sIdx = nodeIndexMap.get(srcId);
    const tIdx = nodeIndexMap.get(tgtId);

    if (sIdx !== undefined && tIdx !== undefined) {
      const s = nodes[sIdx];
      const t = nodes[tIdx];

      ePosAttr.setXYZ(i * 2, s.x, s.y, s.z);
      ePosAttr.setXYZ(i * 2 + 1, t.x, t.y, t.z);

      const sMod = graphGroupOf(s.node);
      const tMod = graphGroupOf(t.node);
      const isCrossing = isCrossingEdge(link.type) || (sMod && tMod && sMod !== tMod);
      const edgeHex = isCrossing
        ? "#a45138"
        : getModuleColor(sMod, moduleOrder) || getEdgeColor(link.type);
      const edgeColor = new THREE.Color(edgeHex);

      eColAttr.setXYZ(i * 2, edgeColor.r, edgeColor.g, edgeColor.b);
      eColAttr.setXYZ(i * 2 + 1, edgeColor.r, edgeColor.g, edgeColor.b);

      eTAttr.setX(i * 2, 0);
      eTAttr.setX(i * 2 + 1, 1);

      const seed = ((i * 0.6180339887) % 1);
      eSeedAttr.setX(i * 2, seed);
      eSeedAttr.setX(i * 2 + 1, seed);

      const isCrossingType = link.type === "INVOKES" || link.type === "EXPOSES";
      const isEdgeAllowed = !filteredEdgeTypes.includes(link.type) && s.vis && t.vis &&
        (!connectionsOnly || isCrossingType);

      let edgeAlpha = isEdgeAllowed ? (isCrossing ? 0.68 : 0.28) : 0.0;
      if (isEdgeAllowed) {
        if (activePath3d) {
          edgeAlpha = isEdgeInPath(link, activePath3d) ? 1.0 : 0.06;
        } else if (activeFocusId) {
          const isConnected = srcId === activeFocusId || tgtId === activeFocusId;
          edgeAlpha = isConnected ? 0.95 : 0.08;
        } else if (highlightedEdgeTypes.length) {
          edgeAlpha = highlightedEdgeTypes.includes(link.type) ? 0.95 : 0.04;
        }
      }

      eAlpAttr.setX(i * 2, edgeAlpha);
      eAlpAttr.setX(i * 2 + 1, edgeAlpha);
      eDirAttr.setX(i * 2, isCrossing ? 1.8 : 1.0);
      eDirAttr.setX(i * 2 + 1, isCrossing ? 1.8 : 1.0);
    } else {
      ePosAttr.setXYZ(i * 2, 0, 0, 0);
      ePosAttr.setXYZ(i * 2 + 1, 0, 0, 0);
      eColAttr.setXYZ(i * 2, 0, 0, 0);
      eColAttr.setXYZ(i * 2 + 1, 0, 0, 0);
      eAlpAttr.setX(i * 2, 0);
      eAlpAttr.setX(i * 2 + 1, 0);
      eDirAttr.setX(i * 2, 0);
      eDirAttr.setX(i * 2 + 1, 0);
    }
  });

  ePosAttr.needsUpdate = true;
  eColAttr.needsUpdate = true;
  eTAttr.needsUpdate = true;
  eSeedAttr.needsUpdate = true;
  eAlpAttr.needsUpdate = true;
  eDirAttr.needsUpdate = true;
}

/**
 * Project 3D nodes into 2D screen coordinates.
 */
export function projectNodesToScreen(
  nodes: Node3DPhysicsState[],
  camera: THREE.PerspectiveCamera,
  width: number,
  height: number
) {
  const v = new THREE.Vector3();
  const halfW = width * 0.5;
  const halfH = height * 0.5;

  for (const n of nodes) {
    if (!n.vis) continue;
    v.set(n.x, n.y, n.z).project(camera);
    n.sx = v.x * halfW + halfW;
    n.sy = -v.y * halfH + halfH;
    n.sz = v.z;
    n.sr = (n.node.size || 4) * (200 / Math.max(10, camera.position.distanceTo(new THREE.Vector3(n.x, n.y, n.z))));
  }
}
