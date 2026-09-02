import { getNodeColor } from "@/lib/graphStyle";
import type { GraphNode, GraphLink } from "@/lib/types";

export interface DomHoverTooltip {
  update: (node: GraphNode | null, links: GraphLink[], screenX: number, screenY: number, containerW: number, containerH: number) => void;
  destroy: () => void;
}

/**
 * Creates a zero-render direct DOM hover tooltip for 3D graphs.
 */
export function createDomHoverTooltip(container: HTMLElement): DomHoverTooltip {
  const el = document.createElement("div");
  el.className = "absolute top-0 left-0 z-30 pointer-events-none transition-opacity duration-100 select-none";
  el.style.opacity = "0";
  el.style.willChange = "transform, opacity";
  container.appendChild(el);

  let lastNodeId: string | null = null;

  const update = (
    node: GraphNode | null,
    links: GraphLink[],
    screenX: number,
    screenY: number,
    containerW: number,
    containerH: number
  ) => {
    if (!node) {
      if (lastNodeId !== null) {
        el.style.opacity = "0";
        lastNodeId = null;
      }
      return;
    }

    const posX = Math.min(containerW - 270, Math.max(12, screenX + 16));
    const posY = Math.min(containerH - 160, Math.max(12, screenY + 16));
    el.style.transform = `translate3d(${posX}px, ${posY}px, 0)`;

    if (node.id !== lastNodeId) {
      lastNodeId = node.id;
      const nodeColor = getNodeColor(node.type);
      const callers = links.filter((l) => (typeof l.target === "object" ? (l.target as any).id : l.target) === node.id).length;
      const callees = links.filter((l) => (typeof l.source === "object" ? (l.source as any).id : l.source) === node.id).length;

      el.innerHTML = `
        <div class="bg-[#fffefa]/95 px-3 py-2.5 rounded-lg border border-[#d4cfc3] shadow-xl w-64 space-y-1.5">
          <div class="flex items-center justify-between gap-1.5">
            <div class="flex items-center gap-1.5 min-w-0">
              <span data-role="color" class="w-2.5 h-2.5 rounded-full flex-shrink-0"></span>
              <span data-role="label" class="font-bold text-xs text-[#252821] truncate"></span>
            </div>
            <span data-role="type" class="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded bg-[#eeeae1] text-[#6e7168] flex-shrink-0"></span>
          </div>
          <div data-role="path" class="text-2xs font-mono text-[#6e7168] truncate"></div>
          <div class="grid grid-cols-2 gap-2 pt-1 border-t border-[#e7e2d8] text-2xs text-[#6e7168]">
            <div>Incoming: <b data-role="incoming" class="text-[#252821]"></b></div>
            <div>Outgoing: <b data-role="outgoing" class="text-[#252821]"></b></div>
          </div>
          <div class="text-2xs text-[#6e7168] pt-0.5 flex items-center justify-between">
            <span>Click to focus</span>
            <span>Shift+Click local path</span>
          </div>
        </div>
      `;
      const color = el.querySelector<HTMLElement>("[data-role='color']");
      const label = el.querySelector<HTMLElement>("[data-role='label']");
      const type = el.querySelector<HTMLElement>("[data-role='type']");
      const path = el.querySelector<HTMLElement>("[data-role='path']");
      const incoming = el.querySelector<HTMLElement>("[data-role='incoming']");
      const outgoing = el.querySelector<HTMLElement>("[data-role='outgoing']");
      if (color) color.style.background = nodeColor;
      if (label) label.textContent = node.label;
      if (type) type.textContent = node.type;
      if (path) {
        path.textContent = node.path ?? "";
        path.style.display = node.path ? "block" : "none";
      }
      if (incoming) incoming.textContent = String(callers);
      if (outgoing) outgoing.textContent = String(callees);
      el.style.opacity = "1";
    }
  };

  const destroy = () => {
    el.remove();
  };

  return { update, destroy };
}
