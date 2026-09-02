import type { GraphNode } from "@/lib/types";

export interface ProjectedLabel {
  id: string;
  label: string;
  type: string;
  color: string;
  x: number;
  y: number;
  visible: boolean;
  opacity: number;
  isFocused: boolean;
  isPath: boolean;
}

interface Props {
  labels: ProjectedLabel[];
  onSelectNode: (nodeId: string) => void;
}

export default function Graph3DLabels({ labels, onSelectNode }: Props) {
  if (labels.length === 0) return null;

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden z-10">
      {labels.map((item) => {
        if (!item.visible) return null;

        return (
          <div
            key={item.id}
            onClick={(e) => {
              e.stopPropagation();
              onSelectNode(item.id);
            }}
            className={`absolute pointer-events-auto cursor-pointer transition-opacity duration-150 -translate-x-1/2 -translate-y-1/2 flex items-center gap-1.5 px-2 py-0.5 rounded-full text-2xs shadow-sm select-none ${
              item.isPath
                ? "bg-[#a45138] text-white font-bold ring-2 ring-[#e2ddd1]"
                : item.isFocused
                ? "bg-[#315b47] text-white font-bold ring-2 ring-[#e2ddd1]"
                : "bg-white/90 dark:bg-slate-900/90 text-[#1a1d23] dark:text-slate-100 border border-[#dfe2e8] hover:bg-white"
            }`}
            style={{
              left: `${item.x}px`,
              top: `${item.y}px`,
              opacity: item.opacity,
            }}
          >
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ background: item.color }}
            />
            <span className="truncate max-w-[140px]">{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}
