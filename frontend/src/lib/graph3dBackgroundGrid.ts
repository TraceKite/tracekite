import * as THREE from "three";

/**
 * Creates subtle ambient spatial depth particles (only rendered in dark mode if needed).
 */
export function createStarfield(_count: number = 0, _radius: number = 400): THREE.Points {
  const geo = new THREE.BufferGeometry();
  const mat = new THREE.PointsMaterial({
    size: 1,
    transparent: true,
    opacity: 0,
    visible: false,
  });
  return new THREE.Points(geo, mat);
}

/**
 * Creates a subtle architectural coordinate radar grid plane at the base of the scene.
 */
export function createRadarGrid(radius: number = 60, yOffset: number = -30): THREE.Group {
  const group = new THREE.Group();
  group.position.y = yOffset;

  // Concentric Rings
  const ringRadii = [radius * 0.33, radius * 0.66, radius];
  ringRadii.forEach((r, idx) => {
    const ringGeo = new THREE.BufferGeometry();
    const pts: number[] = [];
    const segments = 64;
    for (let i = 0; i <= segments; i++) {
      const theta = (i / segments) * Math.PI * 2;
      pts.push(Math.cos(theta) * r, 0, Math.sin(theta) * r);
    }
    ringGeo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    const ringMat = new THREE.LineBasicMaterial({
      color: 0xd4cfc3,
      transparent: true,
      opacity: idx === 2 ? 0.20 : 0.12,
    });
    group.add(new THREE.Line(ringGeo, ringMat));
  });

  // Cross axes
  const axisGeo = new THREE.BufferGeometry();
  const axisPts = [
    -radius, 0, 0,
    radius, 0, 0,
    0, 0, -radius,
    0, 0, radius,
  ];
  axisGeo.setAttribute("position", new THREE.Float32BufferAttribute(axisPts, 3));
  const axisMat = new THREE.LineBasicMaterial({
    color: 0xd4cfc3,
    transparent: true,
    opacity: 0.14,
  });
  group.add(new THREE.LineSegments(axisGeo, axisMat));

  return group;
}
