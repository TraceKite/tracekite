import type { RefObject } from "react";

import { getNodeColor } from "@/lib/graphStyle";
import type { GraphNode } from "@/lib/types";

interface Props {
  node: GraphNode | null;
  /** Positioned imperatively by the canvas on every pointer move. */
  cardRef: RefObject<HTMLDivElement | null>;
}

export default function Graph2DHoverCard({ node, cardRef }: Props) {
  if (!node) return null;
  return (
    <div
      ref={cardRef}
      className="absolute z-20 pointer-events-none -translate-x-1/2 -translate-y-[120%]
                 rounded-md border border-[#d4cfc3] bg-[#fffefa]/95 px-3 py-2 text-xs
                 text-[#252821] shadow-lg"
    >
      <div className="flex items-center gap-2 font-semibold">
        <span className="h-2 w-2 rounded-full"
          style={{ backgroundColor: getNodeColor(node.type) }} />
        <span>{node.label}</span>
      </div>
      <div className="mt-1 font-mono text-2xs text-[#6e7168]">{node.type}</div>
      {node.path && (
        <div className="max-w-[260px] truncate font-mono text-2xs text-[#6e7168]">
          {node.path}
        </div>
      )}
    </div>
  );
}
