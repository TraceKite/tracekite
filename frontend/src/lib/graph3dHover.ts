import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

/**
 * Finds the front-most hovered node under the cursor in screen space.
 */
export function findHoveredNode(
  nodes: Node3DPhysicsState[],
  cursorX: number,
  cursorY: number
): Node3DPhysicsState | null {
  let hovered: Node3DPhysicsState | null = null;

  for (const pn of nodes) {
    if (!pn.vis || pn.sz > 1.0) continue;
    const dx = pn.sx - cursorX;
    const dy = pn.sy - cursorY;
    const hitRadius = Math.max(14, pn.sr + 10);
    if (dx * dx + dy * dy <= hitRadius * hitRadius) {
      if (!hovered || pn.sz < hovered.sz) {
        hovered = pn;
      }
    }
  }

  return hovered;
}
