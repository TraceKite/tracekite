import * as THREE from "three";
import type { Camera3DState } from "@/hooks/useGraph3DInteraction";

/**
 * Updates camera position with smooth damping towards target look.
 */
export function updateDampedCamera(
  camera: THREE.PerspectiveCamera,
  c: Camera3DState,
  dt: number,
  autoOrbit: boolean
) {
  if (autoOrbit && !c.isDragging) {
    c.tTheta += dt * 0.12;
  }

  const damp = 1 - Math.pow(0.0015, dt);
  c.theta += (c.tTheta - c.theta) * damp;
  c.phi += (c.tPhi - c.phi) * damp;
  c.dist += (c.tDist - c.dist) * damp;
  c.currLook.lerp(c.targetLook, damp);

  const sinPhi = Math.sin(c.phi);
  const cosPhi = Math.cos(c.phi);
  camera.position.x = c.currLook.x + c.dist * sinPhi * Math.cos(c.theta);
  camera.position.y = c.currLook.y + c.dist * cosPhi;
  camera.position.z = c.currLook.z + c.dist * sinPhi * Math.sin(c.theta);
  camera.lookAt(c.currLook);
}
