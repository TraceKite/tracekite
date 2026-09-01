import { useEffect, type RefObject } from "react";

import type { Camera3DState } from "@/hooks/useGraph3DInteraction";
import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

export function useGraph3DCameraFrame(
  cameraRef: RefObject<Camera3DState>,
  physicsNodesRef: RefObject<Node3DPhysicsState[]>,
  sceneKey: string,
) {
  useEffect(() => {
    const nodes = physicsNodesRef.current;
    if (!nodes.length) return;
    const center = nodes.reduce(
      (sum, node) => ({ x: sum.x + node.x, y: sum.y + node.y, z: sum.z + node.z }),
      { x: 0, y: 0, z: 0 },
    );
    center.x /= nodes.length;
    center.y /= nodes.length;
    center.z /= nodes.length;
    const radius = nodes.reduce((largest, node) => Math.max(largest,
      Math.hypot(node.x - center.x, node.y - center.y, node.z - center.z)), 0);
    const distance = Math.max(90, Math.min(145, radius * 1.9));
    const camera = cameraRef.current;
    camera.baseDist = distance;
    camera.dist = distance;
    camera.tDist = distance;
    camera.currLook.set(center.x, center.y, center.z);
    camera.targetLook.set(center.x, center.y, center.z);
  }, [cameraRef, physicsNodesRef, sceneKey]);
}
