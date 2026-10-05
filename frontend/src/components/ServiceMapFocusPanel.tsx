import { useGraphStore } from "@/store/graphStore";

interface ServiceMapFocusPanelProps {
  node: any;
  incoming: any[];
  outgoing: any[];
  onClear: () => void;
}

export default function ServiceMapFocusPanel({
  node, incoming, outgoing, onClear,
}: ServiceMapFocusPanelProps) {
  const { setSelectedEdge, setAppMode, traceFrom, traceTo, setTraceEndpoints } =
    useGraphStore();

  return (
    <div className="absolute top-3 right-3 z-30 w-72 max-h-[70%] overflow-y-auto rounded-lg
                    bg-white border border-[#dfe2e8] shadow-lg text-xs">
      <div className="flex items-start justify-between gap-2 p-3 border-b border-[#dfe2e8]">
        <div className="min-w-0">
          <div className="font-bold text-[#1a1d23] truncate">{node.name}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <span className="text-2xs text-[#8b929e] bg-slate-100 px-1.5 py-0.5 rounded">
              {node.kind}
            </span>
            {node.is_gateway && (
              <span className="text-2xs text-[#274a3a] bg-[#315b47]/10 px-1.5 py-0.5 rounded">
                Gateway
              </span>
            )}
          </div>
          {(node.repo_ids ?? []).length > 0 && (
            <div className="mt-2 text-2xs text-[#8b929e] leading-relaxed">
              built from {(node.repo_ids as string[]).join(", ")}
            </div>
          )}
        </div>
        <button onClick={onClear}
                className="shrink-0 text-[#8b929e] hover:text-[#1a1d23] px-1"
                aria-label="Clear selection">×</button>
      </div>
      {node.kind === "service" && (
        <div className="flex gap-1.5 px-3 py-2 border-b border-[#dfe2e8]">
          <button
            onClick={() => { setTraceEndpoints(node.id, traceTo); setAppMode("trace"); }}
            className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-[#315b47]/10
                       text-[#274a3a] hover:bg-[#315b47]/15 transition-colors">
            Trace from here
          </button>
          <button
            onClick={() => { setTraceEndpoints(traceFrom, node.id); setAppMode("trace"); }}
            className="flex-1 text-2xs px-2 py-1.5 rounded-md bg-[#315b47]/10
                       text-[#274a3a] hover:bg-[#315b47]/15 transition-colors">
            Trace to here
          </button>
        </div>
      )}
      {([["Called by", incoming, "source"],
         ["Calls", outgoing, "target"]] as const).map(([label, links, end]) => (
        <div key={label} className="p-3 border-b border-slate-200 last:border-0">
          <div className="uppercase tracking-wider text-2xs text-[#8b929e] mb-1.5">
            {label} ({links.length})
          </div>
          {links.length === 0 ? (
            <div className="text-2xs text-[#5c636d]">nothing recorded</div>
          ) : links.map((link: any, index: number) => {
            const other = link[end];
            const name = typeof other === "object" ? other?.name ?? other?.id : other;
            return (
              <button key={index} onClick={() => setSelectedEdge(link)}
                      className="w-full text-left py-1 px-1.5 rounded hover:bg-slate-100
                                 flex items-center justify-between gap-2">
                <span className="truncate text-[#1a1d23]">{name}</span>
                <span className="shrink-0 text-2xs text-[#8b929e]">
                  {link.confidence != null ? Number(link.confidence).toFixed(2) : ""}
                </span>
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
