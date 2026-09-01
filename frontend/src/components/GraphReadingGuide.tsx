import type { ViewMode } from "@/lib/types";

export default function GraphReadingGuide({
  moduleOrder,
  viewMode,
}: {
  moduleOrder: string[];
  viewMode: ViewMode;
}) {
  if (moduleOrder.length < 2) return null;
  return (
    <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/80 p-2.5 shadow-xs">
      <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
        Reading the graph
      </span>
      <div className="flex items-center gap-2">
        <span className="h-[2.5px] w-4 shrink-0 rounded-full bg-[#a45138]" />
        <span className="text-2xs font-medium text-slate-800">crosses a module</span>
      </div>
      <div className="border-t border-slate-200/80 pt-1.5">
        <p className="text-2xs leading-relaxed text-slate-600">
          {moduleOrder.length} groups in {viewMode}. Expand a bounded exact subset; search reaches any node.
        </p>
      </div>
    </div>
  );
}
