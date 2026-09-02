import { getNodeColor } from "@/lib/graphStyle";
import type { GraphNode, GraphLink } from "@/lib/types";

interface Props {
  node: GraphNode | null;
  links: GraphLink[];
  x: number;
  y: number;
  visible: boolean;
}

export default function Graph3DHoverCard({ node, links, x, y, visible }: Props) {
  if (!visible || !node) return null;

  const nodeColor = getNodeColor(node.type);
  const callers = links.filter((l) => (typeof l.target === "object" ? (l.target as any).id : l.target) === node.id).length;
  const callees = links.filter((l) => (typeof l.source === "object" ? (l.source as any).id : l.source) === node.id).length;

  const posX = Math.max(12, x + 16);
  const posY = Math.max(12, y + 16);

  return (
    <div
      className="absolute top-0 left-0 z-30 pointer-events-none transition-transform duration-75 select-none"
      style={{ transform: `translate(${posX}px, ${posY}px)` }}
    >
      <div className="bg-white/95 dark:bg-slate-900/95 backdrop-blur-md px-3 py-2.5 rounded-xl border border-[#dfe2e8] dark:border-slate-800 shadow-xl w-64 space-y-1.5 animate-in fade-in zoom-in-95 duration-100">
        <div className="flex items-center justify-between gap-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ background: nodeColor }}
            />
            <span className="font-bold text-xs text-[#1a1d23] dark:text-slate-100 truncate">
              {node.label}
            </span>
          </div>
          <span className="text-2xs font-mono font-semibold uppercase px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-[#5c6370] dark:text-slate-400 flex-shrink-0">
            {node.type}
          </span>
        </div>

        {node.path && (
          <div className="text-2xs font-mono text-[#8b929e] dark:text-slate-400 truncate">
            {node.path}
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 pt-1 border-t border-[#edf0f5] dark:border-slate-800 text-2xs text-[#5c6370] dark:text-slate-400">
          <div>
            <span className="text-[#8b929e]">Callers: </span>
            <b className="text-[#1a1d23] dark:text-slate-200">{callers}</b>
          </div>
          <div>
            <span className="text-[#8b929e]">Callees: </span>
            <b className="text-[#1a1d23] dark:text-slate-200">{callees}</b>
          </div>
        </div>

        <div className="text-2xs text-[#8b929e] pt-0.5 italic flex items-center justify-between">
          <span>Click to focus</span>
          <span>Shift+Click trace</span>
        </div>
      </div>
    </div>
  );
}
