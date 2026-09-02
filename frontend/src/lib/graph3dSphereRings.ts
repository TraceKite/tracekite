import * as THREE from "three";

/**
 * Creates subtle celestial guide rings for 3D Sphere mode.
 */
export function createSphereRings(radius: number = 44): THREE.Group {
  const sphereRings = new THREE.Group();
  const ringMat = new THREE.LineBasicMaterial({
    color: 0xd4cfc3,
    transparent: true,
    opacity: 0.25,
  });

  const ringGeo1 = new THREE.BufferGeometry();
  const ringGeo2 = new THREE.BufferGeometry();
  const ringGeo3 = new THREE.BufferGeometry();
  const pts1: THREE.Vector3[] = [];
  const pts2: THREE.Vector3[] = [];
  const pts3: THREE.Vector3[] = [];

  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * Math.PI * 2;
    pts1.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
    pts2.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0));
    pts3.push(new THREE.Vector3(0, Math.cos(a) * radius, Math.sin(a) * radius));
  }

  ringGeo1.setFromPoints(pts1);
  ringGeo2.setFromPoints(pts2);
  ringGeo3.setFromPoints(pts3);

  sphereRings.add(new THREE.Line(ringGeo1, ringMat));
  sphereRings.add(new THREE.Line(ringGeo2, ringMat));
  sphereRings.add(new THREE.Line(ringGeo3, ringMat));
  sphereRings.visible = false;

  return sphereRings;
}

export function disposeSphereRings(sphereRings: THREE.Group) {
  sphereRings.children.forEach((child) => {
    if (child instanceof THREE.Line) {
      child.geometry.dispose();
      (child.material as THREE.Material).dispose();
    }
  });
}
