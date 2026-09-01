import { getNodeColor } from "./graphStyle.ts";
import { getNeighbors } from "./graph3dPath.ts";
import type { GraphLink } from "./types.ts";
import type { Node3DPhysicsState } from "./graph3dPhysics.ts";

export interface DomLabelPool {
  elements: HTMLDivElement[];
  destroy: () => void;
}

export function shouldExposeLabel(showLabels: boolean, isHighlight: boolean): boolean {
  return showLabels || isHighlight;
}

/**
 * Creates a reusable pool of DOM billboard label elements styled as crisp micro-badges.
 */
export function createDomLabelPool(
  container: HTMLElement,
  poolSize: number = 24,
  onSelectNode?: (nodeId: string, pathMode?: boolean, open?: boolean) => void
): DomLabelPool {
  const labelLayer = document.createElement("div");
  labelLayer.style.position = "absolute";
  labelLayer.style.inset = "0";
  labelLayer.style.pointerEvents = "none";
  labelLayer.style.overflow = "hidden";
  labelLayer.style.zIndex = "3";
  container.appendChild(labelLayer);

  const elements: HTMLDivElement[] = [];

  for (let i = 0; i < poolSize; i++) {
    const el = document.createElement("div");
    el.style.position = "absolute";
    el.style.transform = "translate(-50%, -50%)";
    el.style.whiteSpace = "nowrap";
    el.style.fontSize = "10.5px";
    el.style.fontWeight = "600";
    el.style.letterSpacing = "0.01em";
    el.style.color = "#252821";
    el.style.background = "rgba(255, 254, 250, 0.96)";
    el.style.border = "1px solid rgba(212, 207, 195, 0.95)";
    el.style.borderRadius = "6px";
    el.style.padding = "2px 7px";
    el.style.boxShadow = "0 1px 4px rgba(0,0,0,0.06)";
    el.style.willChange = "transform, opacity";
    el.style.opacity = "0";
    el.style.transition = "opacity 0.12s ease-out";
    el.style.cursor = "pointer";
    el.style.pointerEvents = "none";
    el.setAttribute("aria-hidden", "true");
    el.tabIndex = -1;

    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const nid = el.dataset.nodeId;
      if (nid && onSelectNode) onSelectNode(nid, e.shiftKey, e.detail >= 2);
    });
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      const nid = el.dataset.nodeId;
      if (nid && onSelectNode) onSelectNode(nid, e.shiftKey);
    });

    labelLayer.appendChild(el);
    elements.push(el);
  }

  return {
    elements,
    destroy: () => {
      if (labelLayer.parentNode === container) {
        container.removeChild(labelLayer);
      }
    },
  };
}

/**
 * Updates billboard label positions and priorities.
 */
export function updateDomLabels(
  pool: DomLabelPool,
  nodes: Node3DPhysicsState[],
  links: GraphLink[],
  width: number,
  height: number,
  selectedId: string | null,
  hoverId: string | null,
  path: string[] | null,
  showLabels: boolean,
  maxLabels: number = pool.elements.length,
) {
  const activeFocus = selectedId || hoverId;
  const neighbors = activeFocus ? getNeighbors(activeFocus, links) : null;
  const pathSet = path ? new Set(path) : null;

  const candidates = nodes.filter((n) => {
    if (!n.vis || n.sz > 1.0) return false;
    if (n.sx < 30 || n.sx > width - 30 || n.sy < 30 || n.sy > height - 30) return false;
    return true;
  });

  candidates.sort((a, b) => {
    if (pathSet) {
      const aP = pathSet.has(a.id) ? 1 : 0;
      const bP = pathSet.has(b.id) ? 1 : 0;
      if (aP !== bP) return bP - aP;
    }
    if (activeFocus) {
      const aF = a.id === activeFocus ? 3 : neighbors?.has(a.id) ? 2 : 0;
      const bF = b.id === activeFocus ? 3 : neighbors?.has(b.id) ? 2 : 0;
      if (aF !== bF) return bF - aF;
    }
    if (a.degree !== b.degree) return b.degree - a.degree;
    return (b.node.size || 1) - (a.node.size || 1);
  });

  const chosen: Node3DPhysicsState[] = [];
  const occupied: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  for (const candidate of candidates) {
    const prioritized = candidate.id === activeFocus || pathSet?.has(candidate.id);
    const labelWidth = Math.min(160, Math.max(48, candidate.node.label.length * 6.3 + 18));
    const rect = {
      left: candidate.sx - labelWidth / 2,
      right: candidate.sx + labelWidth / 2,
      top: candidate.sy - candidate.sr - 25,
      bottom: candidate.sy - candidate.sr - 5,
    };
    const overlaps = occupied.some((item) =>
      rect.left < item.right && rect.right > item.left &&
      rect.top < item.bottom && rect.bottom > item.top);
    if (!prioritized && overlaps) continue;
    chosen.push(candidate);
    occupied.push(rect);
    if (chosen.length >= Math.min(pool.elements.length, maxLabels)) break;
  }

  const count = chosen.length;
  for (let i = 0; i < count; i++) {
    const el = pool.elements[i];
    const n = chosen[i];
    el.dataset.nodeId = n.id;
    el.textContent = n.node.label;

    const isHighlight = Boolean(
      pathSet?.has(n.id) ||
      (activeFocus && (n.id === activeFocus || neighbors?.has(n.id))),
    );
    if (isHighlight) {
      const col = getNodeColor(n.node.type);
      el.style.borderColor = col;
      el.style.boxShadow = `0 0 0 1px ${col}`;
      el.style.fontWeight = "700";
    } else {
      el.style.borderColor = "rgba(212, 207, 195, 0.95)";
      el.style.boxShadow = "none";
      el.style.fontWeight = "600";
    }

    el.style.transform = `translate3d(${n.sx}px, ${n.sy - n.sr - 12}px, 0) translate(-50%, -50%)`;
    const exposed = shouldExposeLabel(showLabels, isHighlight);
    el.style.opacity = exposed ? "1" : "0";
    el.style.pointerEvents = exposed ? "auto" : "none";
    el.setAttribute("aria-hidden", exposed ? "false" : "true");
    el.tabIndex = exposed ? 0 : -1;
    if (exposed) {
      el.setAttribute("role", "button");
      el.setAttribute("aria-label", `${n.node.label}, ${n.node.type}`);
      el.title = "Click to focus; Shift+click for a directed local path";
    } else {
      el.removeAttribute("role");
      el.removeAttribute("aria-label");
      el.removeAttribute("title");
      el.textContent = "";
    }
  }

  for (let i = count; i < pool.elements.length; i++) {
    const el = pool.elements[i];
    el.style.opacity = "0";
    el.style.pointerEvents = "none";
    el.setAttribute("aria-hidden", "true");
    el.tabIndex = -1;
    el.removeAttribute("role");
    el.removeAttribute("aria-label");
    el.removeAttribute("title");
    delete el.dataset.nodeId;
    el.textContent = "";
  }
}
