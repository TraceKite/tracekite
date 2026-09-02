import * as THREE from "three";

/**
 * Node vertex shader for GPU-accelerated Point Clouds with bounded size attenuation.
 */
export const NODE_VERTEX_SHADER = `
  attribute vec3 aColor;
  attribute float aSize;
  attribute float aAlpha;
  attribute float aScale;
  varying vec3 vColor;
  varying float vAlpha;
  uniform float uPx;
  uniform float uMul;

  void main() {
    vColor = aColor;
    vAlpha = aAlpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float pSize = aSize * aScale * uMul * uPx / max(-mv.z, 1.0);
    gl_PointSize = clamp(pSize, 3.5, 44.0);
    gl_Position = projectionMatrix * mv;
  }
`;

/**
 * Outer Halo shader: Soft luminous colorful aura.
 */
export const HALO_FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
    float halo = pow(1.0 - d, 2.0);
    gl_FragColor = vec4(vColor, halo * 0.12 * vAlpha);
  }
`;

/**
 * Inner Bead shader: Crisp, high-contrast solid bead with specular glass highlight.
 */
export const BEAD_FRAGMENT_SHADER = `
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    float d = length(gl_PointCoord - 0.5) * 2.0;
    if (d > 1.0) discard;
    float disc = smoothstep(1.0, 0.78, d);
    float spec = smoothstep(0.8, 0.0, length(gl_PointCoord - vec2(0.35, 0.35)) * 2.6);
    vec3 c = mix(vColor, vec3(1.0), spec * 0.18);
    gl_FragColor = vec4(c, disc * 0.95 * vAlpha);
  }
`;

/**
 * Edge line vertex shader.
 */
export const EDGE_VERTEX_SHADER = `
  attribute vec3 aColor;
  attribute float aT;
  attribute float aSeed;
  attribute float aAlpha;
  attribute float aDir;
  varying vec3 vColor;
  varying float vT;
  varying float vSeed;
  varying float vAlpha;
  varying float vDir;

  void main() {
    vColor = aColor;
    vT = aT;
    vSeed = aSeed;
    vAlpha = aAlpha;
    vDir = aDir;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

/**
 * Edge line fragment shader with travelling luminous signal wave pulses.
 */
export const EDGE_FRAGMENT_SHADER = `
  precision mediump float;
  varying vec3 vColor;
  varying float vT;
  varying float vSeed;
  varying float vAlpha;
  varying float vDir;
  uniform float uTime;
  uniform float uFlow;

  void main() {
    float head = fract(vSeed + uTime * 0.16);
    float d = abs(vT - head);
    d = min(d, 1.0 - d);
    float pulse = exp(-pow(d * 7.5, 2.0)) * vDir * uFlow;
    vec3 lineCol = mix(vColor, vec3(1.0), pulse * 0.28);
    gl_FragColor = vec4(lineCol, vAlpha * (0.48 + 0.52 * pulse));
  }
`;

export function createNodeHaloMaterial(isLight: boolean = true) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uPx: { value: 300 },
      uMul: { value: 1.8 },
    },
    vertexShader: NODE_VERTEX_SHADER,
    fragmentShader: HALO_FRAGMENT_SHADER,
    transparent: true,
    blending: THREE.NormalBlending,
    depthWrite: false,
  });
}

export function createNodeBeadMaterial(isLight: boolean = true) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uPx: { value: 300 },
      uMul: { value: 0.95 },
    },
    vertexShader: NODE_VERTEX_SHADER,
    fragmentShader: BEAD_FRAGMENT_SHADER,
    transparent: true,
    blending: THREE.NormalBlending,
    depthWrite: true,
  });
}

export function createEdgeFlowMaterial(isLight: boolean = true) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uFlow: { value: 1.0 },
    },
    vertexShader: EDGE_VERTEX_SHADER,
    fragmentShader: EDGE_FRAGMENT_SHADER,
    transparent: true,
    blending: THREE.NormalBlending,
    depthWrite: false,
  });
}
