import { useEffect, useRef, type RefObject } from "react";

import type { Camera3DState } from "@/hooks/useGraph3DInteraction";
import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

/**
 * Frames the camera on a newly drawn scene.
 *
 * `sceneKey` is what deserves a fresh frame — scope, view mode, layout, the
 * expanded module. It excludes the selected node: focusing one rebuilds the
 * cloud at the same anchor radius, so re-framing there only threw the user's
 * zoom away. `layoutRevision` changes whenever the physics nodes are rebuilt,
 * which is how a scene that has never been framed still gets its first frame
 * once its nodes exist.
 */
export function useGraph3DCameraFrame(
  cameraRef: RefObject<Camera3DState>,
  physicsNodesRef: RefObject<Node3DPhysicsState[]>,
  sceneKey: string,
  layoutRevision: number,
) {
  const framedRef = useRef<string | null>(null);

  useEffect(() => {
    const nodes = physicsNodesRef.current;
    if (!nodes.length || framedRef.current === sceneKey) return;
    framedRef.current = sceneKey;
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
    // Re-scale the zoom the user chose rather than dropping it: the toolbar
    // reads zoom as baseDist/tDist, so resetting one without the other left
    // the readout describing a camera that was no longer there.
    const distanceRatio = camera.baseDist > 0 ? camera.tDist / camera.baseDist : 1;
    camera.baseDist = distance;
    camera.tDist = distance * distanceRatio;
    // dist and currLook are the damper's to move, so the frame eases in
    // instead of teleporting.
    camera.targetLook.set(center.x, center.y, center.z);
  }, [cameraRef, layoutRevision, physicsNodesRef, sceneKey]);
}
