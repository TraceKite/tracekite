import * as THREE from "three";
import { MODULE_HUE_LIST, graphGroupOf } from "@/lib/graphStyle";
import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

export interface ClusterInfo {
  id: string;
  name: string;
  count: number;
  apiCount: number;
  x: number;
  y: number;
  z: number;
  sx: number;
  sy: number;
  sz: number;
  color: string;
}

export interface ClusterHoloPool {
  elements: HTMLDivElement[];
  onFocus?: (cluster: ClusterInfo) => void;
  destroy: () => void;
}

/**
 * Computes 3D centroids and metrics for architectural clusters.
 */
export function computeClusterCentroids(nodes: Node3DPhysicsState[]): ClusterInfo[] {
  const map = new Map<string, { x: number; y: number; z: number; count: number; apiCount: number }>();

  nodes.forEach((n) => {
    if (!n.vis) return;
    const mod = graphGroupOf(n.node);
    const cur = map.get(mod) || { x: 0, y: 0, z: 0, count: 0, apiCount: 0 };
    cur.x += n.x;
    cur.y += n.y;
    cur.z += n.z;
    cur.count++;
    if (n.node.type === "ApiEndpoint") cur.apiCount++;
    map.set(mod, cur);
  });

  const clusters: ClusterInfo[] = [];
  let idx = 0;
  map.forEach((val, id) => {
    if (val.count < 3) return;
    const inv = 1 / val.count;
    clusters.push({
      id,
      name: id,
      count: val.count,
      apiCount: val.apiCount,
      x: val.x * inv,
      y: val.y * inv + 4.5,
      z: val.z * inv,
      sx: 0,
      sy: 0,
      sz: 0,
      color: MODULE_HUE_LIST[idx % MODULE_HUE_LIST.length],
    });
    idx++;
  });

  return clusters;
}

/**
 * Creates DOM billboard pool for 3D holographic cluster labels.
 */
export function createClusterHoloPool(
  container: HTMLElement,
  onFocusCluster?: (cluster: ClusterInfo) => void
): ClusterHoloPool {
  const layer = document.createElement("div");
  layer.style.position = "absolute";
  layer.style.inset = "0";
  layer.style.pointerEvents = "none";
  layer.style.overflow = "hidden";
  layer.style.zIndex = "4";
  container.appendChild(layer);

  const elements: HTMLDivElement[] = [];

  for (let i = 0; i < 8; i++) {
    const el = document.createElement("div");
    el.style.position = "absolute";
    el.style.transform = "translate(-50%, -50%)";
    el.style.display = "flex";
    el.style.alignItems = "center";
    el.style.gap = "6px";
    el.style.padding = "3px 8px 3px 6px";
    el.style.borderRadius = "99px";
    el.style.background = "rgba(255, 254, 250, 0.96)";
    el.style.border = "1px solid rgba(212, 207, 195, 0.95)";
    el.style.boxShadow = "0 2px 8px rgba(0, 0, 0, 0.08)";
    el.style.fontSize = "10.5px";
    el.style.fontWeight = "600";
    el.style.letterSpacing = "0.02em";
    el.style.textTransform = "uppercase";
    el.style.color = "#252821";
    el.style.opacity = "0";
    el.style.transition = "opacity 0.2s ease-out";
    el.style.willChange = "transform, opacity";
    el.style.cursor = "pointer";

    layer.appendChild(el);
    elements.push(el);
  }

  return {
    elements,
    onFocus: onFocusCluster,
    destroy: () => {
      if (layer.parentNode === container) container.removeChild(layer);
    },
  };
}

/**
 * Updates cluster positions in 3D projection without React re-renders.
 */
export function updateClusterHolo(
  pool: ClusterHoloPool,
  clusters: ClusterInfo[],
  camera: THREE.Camera,
  width: number,
  height: number,
  onFocus?: (c: ClusterInfo) => void
) {
  const vec = new THREE.Vector3();
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  let visibleCount = 0;
  const ordered = [...clusters].sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));

  ordered.forEach((c) => {
    if (visibleCount >= pool.elements.length) return;
    vec.set(c.x, c.y, c.z);
    vec.project(camera);

    c.sx = (vec.x * 0.5 + 0.5) * width;
    c.sy = (-vec.y * 0.5 + 0.5) * height;
    c.sz = vec.z;

    if (c.sz < 1.0 && c.sx > 0 && c.sx < width && c.sy > 0 && c.sy < height) {
      const labelWidth = Math.min(210, Math.max(88, c.name.length * 7 + 42));
      const rect = {
        left: c.sx - labelWidth / 2,
        right: c.sx + labelWidth / 2,
        top: c.sy - 12,
        bottom: c.sy + 12,
      };
      const overlaps = occupied.some((item) =>
        rect.left < item.right && rect.right > item.left &&
        rect.top < item.bottom && rect.bottom > item.top);
      if (overlaps) return;
      occupied.push(rect);
      const el = pool.elements[visibleCount++];
      el.style.transform = `translate(-50%, -50%) translate(${c.sx.toFixed(1)}px, ${c.sy.toFixed(1)}px)`;
      el.style.opacity = "0.95";
      el.style.pointerEvents = "auto";
      const contentKey = `${c.id}:${c.count}:${c.color}`;
      if (el.dataset.contentKey !== contentKey) {
        el.dataset.contentKey = contentKey;
        el.replaceChildren();
        const dot = document.createElement("span");
        dot.style.cssText = `width:7px;height:7px;border-radius:50%;background:${c.color}`;
        const name = document.createElement("span");
        name.textContent = c.name;
        const count = document.createElement("b");
        count.style.cssText = "font-size:9px;color:#6e7168;font-weight:400";
        count.textContent = `(${c.count})`;
        el.append(dot, name, count);
      }
      el.onclick = (e) => {
        e.stopPropagation();
        (onFocus ?? pool.onFocus)?.(c);
      };
    }
  });

  for (let i = visibleCount; i < pool.elements.length; i++) {
    pool.elements[i].style.opacity = "0";
    pool.elements[i].style.pointerEvents = "none";
  }
}
