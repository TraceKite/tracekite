import { Network } from "lucide-react";

export default function ServiceMapStatus({
  nodeCount,
  linkCount,
  focusedName,
  isolatedCount,
}: {
  nodeCount: number;
  linkCount: number;
  focusedName?: string;
  isolatedCount: number;
}) {
  return (
    <div className="absolute left-4 top-4 z-20 flex items-center gap-2 rounded-md
                    border border-[#c9c3b7] bg-[#fffefa]/95 px-2.5 py-1.5
                    text-2xs text-[#6e7168] shadow-sm">
      <Network className="h-3.5 w-3.5 text-[#315b47]" />
      <span className="font-semibold text-[#252821]">
        {focusedName ? `Service · ${focusedName}` : "Service Map"}
      </span>
      <span className="border-l border-[#d4cfc3] pl-2 font-mono">
        {nodeCount} nodes · {linkCount} links
      </span>
      {isolatedCount > 0 && <span className="text-[#6f5723]">{isolatedCount} unconnected</span>}
    </div>
  );
}
