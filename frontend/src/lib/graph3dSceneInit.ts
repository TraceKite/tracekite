import * as THREE from "three";
import {
  createNodeHaloMaterial,
  createNodeBeadMaterial,
  createEdgeFlowMaterial,
} from "@/lib/graph3dShaders";
import { createSphereRings, disposeSphereRings } from "@/lib/graph3dSphereRings";
import { createStarfield, createRadarGrid } from "@/lib/graph3dBackgroundGrid";

export interface Scene3DContext {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  haloPoints: THREE.Points;
  beadPoints: THREE.Points;
  flowLines: THREE.LineSegments;
  sphereRings: THREE.Group;
  starfield: THREE.Points;
  radarGrid: THREE.Group;
  nodeGeo: THREE.BufferGeometry;
  edgeGeo: THREE.BufferGeometry;
  haloMat: THREE.ShaderMaterial;
  beadMat: THREE.ShaderMaterial;
  flowMat: THREE.ShaderMaterial;
}

export function init3DScene(el: HTMLElement, isLight: boolean = true): Scene3DContext {
  const width = el.clientWidth || 800;
  const height = el.clientHeight || 600;

  const scene = new THREE.Scene();
  const bgColor = new THREE.Color(isLight ? "#f4f1e9" : "#20241f");
  scene.background = bgColor;

  const camera = new THREE.PerspectiveCamera(46, width / height, 1, 3000);
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    powerPreference: "high-performance",
  });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  el.appendChild(renderer.domElement);

  const nodeGeo = new THREE.BufferGeometry();
  const edgeGeo = new THREE.BufferGeometry();
  const haloMat = createNodeHaloMaterial(isLight);
  const beadMat = createNodeBeadMaterial(isLight);
  const flowMat = createEdgeFlowMaterial(isLight);

  const uPx = height / (2 * Math.tan((camera.fov * Math.PI) / 360));
  haloMat.uniforms.uPx.value = uPx;
  beadMat.uniforms.uPx.value = uPx;

  const haloPoints = new THREE.Points(nodeGeo, haloMat);
  const beadPoints = new THREE.Points(nodeGeo, beadMat);
  haloPoints.frustumCulled = false;
  beadPoints.frustumCulled = false;

  const flowLines = new THREE.LineSegments(edgeGeo, flowMat);
  flowLines.frustumCulled = false;

  const sphereRings = createSphereRings(44);
  const starfield = createStarfield(450, 480);
  const radarGrid = createRadarGrid(58, -28);

  scene.add(starfield, radarGrid, haloPoints, beadPoints, flowLines, sphereRings);

  return {
    scene,
    camera,
    renderer,
    haloPoints,
    beadPoints,
    flowLines,
    sphereRings,
    starfield,
    radarGrid,
    nodeGeo,
    edgeGeo,
    haloMat,
    beadMat,
    flowMat,
  };
}

export function dispose3DScene(ctx: Scene3DContext, el: HTMLElement) {
  ctx.renderer.dispose();
  ctx.nodeGeo.dispose();
  ctx.edgeGeo.dispose();
  ctx.haloMat.dispose();
  ctx.beadMat.dispose();
  ctx.flowMat.dispose();
  disposeSphereRings(ctx.sphereRings);
  if (ctx.renderer.domElement.parentNode === el) {
    el.removeChild(ctx.renderer.domElement);
  }
}
