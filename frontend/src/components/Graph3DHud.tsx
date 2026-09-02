import { Route, X } from "lucide-react";

import { useGraphStore } from "@/store/graphStore";

export default function Graph3DHud({ onClearPath }: { onClearPath: () => void }) {
  const { activePath3d, nodes } = useGraphStore();
  if (!activePath3d?.length) return null;
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      className="absolute top-4 left-1/2 z-20 flex max-w-[55%] -translate-x-1/2
                 items-center gap-2 rounded-lg border border-[#c9c3b7]
                 bg-[#fffefa]/95 px-3 py-2 shadow-md"
    >
      <Route className="h-3.5 w-3.5 shrink-0 text-[#a45138]" />
      <span className="shrink-0 text-2xs font-semibold text-[#6b6f65]">
        Local directed path
      </span>
      <div className="flex items-center gap-1.5 overflow-x-auto text-xs font-mono">
        {activePath3d.map((id, index) => {
          const node = nodeMap.get(id);
          const label = node?.label || id.split("/").pop() || id;
          const endpoint = index === 0 || index === activePath3d.length - 1;
          return (
            <div key={id} className="flex shrink-0 items-center gap-1.5">
              <span className={`rounded border px-2 py-0.5 text-2xs font-semibold ${
                endpoint
                  ? "border-[#315b47]/35 bg-[#315b47]/10 text-[#274a3a]"
                  : "border-[#d4cfc3] bg-[#f4f1e9] text-[#4b5148]"
              }`}>
                {label}
              </span>
              {index < activePath3d.length - 1 && (
                <span className="font-bold text-[#9b7a31]">→</span>
              )}
            </div>
          );
        })}
      </div>
      <button
        onClick={onClearPath}
        className="shrink-0 rounded p-1 text-[#8a8e84] hover:bg-[#f4f1e9] hover:text-[#252821]"
        title="Clear path"
        aria-label="Clear directed path"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
