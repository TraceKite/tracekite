import { useMemo, useRef, useState } from "react";
import { GitMerge, Loader2, Play, Zap } from "lucide-react";
import ServicePickerModal from "@/components/ServicePickerModal";
import type { ServiceMapNode } from "@/lib/types";
import { useGraphStore } from "@/store/graphStore";

export default function TraceSidebar({
  onTrace, tracing, traceError
}: {
  onTrace: (f: string, t: string, c: number, a: string, h: number, k: number) => void,
  tracing: boolean,
  traceError: any
}) {
  const { traceData, setTraceData, setSelectedEdge, serviceMapData, scopeRepoIds,
          traceFrom, traceTo, setTraceEndpoints } =
    useGraphStore();
  const fromSvc = traceFrom;
  const toSvc = traceTo;
  const setFromSvc = (v: string) => setTraceEndpoints(v, traceTo);
  const setToSvc = (v: string) => setTraceEndpoints(traceFrom, v);
  const [minConf, setMinConf] = useState(0.6);
  const [alt, setAlt] = useState<"service" | "code">("service");
  const [maxHops, setMaxHops] = useState(6);
  const [k, setK] = useState(3);
  const sameEndpoint = Boolean(fromSvc && fromSvc === toSvc);

  // Endpoint suggestions, scoped. The scope decides which services you can
  // PICK; it deliberately does not constrain the path the backend walks —
  // filtering intermediate hops would report "no path" whenever a real route
  // passes through an unselected repo, a false negative in the one view whose
  // whole value is trustworthy evidence.
  const services = useMemo<ServiceMapNode[]>(() => {
    const all = (serviceMapData?.nodes ?? []).filter(
      (node) => node.kind === "service");
    return (scopeRepoIds.length === 0
      ? all
      : all.filter((node) =>
          (node.repo_ids ?? []).some((id) => scopeRepoIds.includes(id))))
      .sort((left, right) =>
        left.name.localeCompare(right.name) || left.id.localeCompare(right.id));
  }, [serviceMapData, scopeRepoIds]);
  const serviceIds = useMemo(
    () => new Set(services.map((service) => service.id)), [services]);
  const serviceLabel = (serviceId: string) =>
    services.find((service) => service.id === serviceId)?.name ?? serviceId;

  const [pickerTarget, setPickerTarget] = useState<"from" | "to" | null>(null);
  const originButtonRef = useRef<HTMLButtonElement>(null);
  const destinationButtonRef = useRef<HTMLButtonElement>(null);
  const closeServicePicker = () => {
    const target = pickerTarget;
    setPickerTarget(null);
    window.requestAnimationFrame(() =>
      (target === "from" ? originButtonRef : destinationButtonRef).current?.focus());
  };

  return (
    <aside className="w-80 flex-shrink-0 border-r border-[#c9c3b7] bg-[#f4f1e9] flex flex-col overflow-hidden z-30 shadow-sm">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h3 className="text-lg font-bold text-[#1a1d23] flex items-center gap-2 mb-1">
            <Zap className="w-5 h-5 text-[#9b7a31]" /> Distributed Trace
          </h3>
          <p className="text-xs text-[#1a1d23] font-medium">How does A reach B, and through which hops?</p>
          <p className="text-2xs text-[#8b929e] mt-1 leading-relaxed">
            One journey, not the whole estate. Ranked paths laid out in hop
            order, every hop backed by a file and line.
          </p>
        </div>

        <div className="space-y-4 bg-slate-50 p-4 rounded-xl border border-slate-200">
          <div>
            <label className="text-xs font-semibold text-[#5c6370] block mb-1">Origin Service</label>
            <button
              ref={originButtonRef}
              onClick={() => setPickerTarget("from")}
              aria-expanded={pickerTarget === "from"}
              aria-haspopup="dialog"
              className="w-full flex items-center justify-between bg-white border border-slate-200 hover:border-[#315b47] rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={fromSvc ? "text-[#1a1d23] font-medium" : "text-[#8b929e]"}>
                {fromSvc
                  ? serviceLabel(fromSvc)
                  : (services[0] ? `e.g. ${services[0].name}` : "Select origin service…")}
              </span>
              <span className="text-2xs text-[#315b47] font-semibold uppercase shrink-0">Choose</span>
            </button>
          </div>

          <div>
            <label className="text-xs font-semibold text-[#5c6370] block mb-1">Destination Service</label>
            <button
              ref={destinationButtonRef}
              onClick={() => setPickerTarget("to")}
              aria-expanded={pickerTarget === "to"}
              aria-haspopup="dialog"
              className="w-full flex items-center justify-between bg-white border border-slate-200 hover:border-[#315b47] rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={toSvc ? "text-[#1a1d23] font-medium" : "text-[#8b929e]"}>
                {toSvc
                  ? serviceLabel(toSvc)
                  : (services[1] ? `e.g. ${services[1].name}` : "Select destination service…")}
              </span>
              <span className="text-2xs text-[#315b47] font-semibold uppercase shrink-0">Choose</span>
            </button>
          </div>

          {pickerTarget && (
            <ServicePickerModal
              title={pickerTarget === "from" ? "Select Origin Service" : "Select Destination Service"}
              selectedService={pickerTarget === "from" ? fromSvc : toSvc}
              onSelect={(serviceId) => {
                if (pickerTarget === "from") setFromSvc(serviceId);
                else setToSvc(serviceId);
              }}
              onClose={closeServicePicker}
            />
          )}

          <div className="pt-2 border-t border-slate-200 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-2xs font-semibold text-[#8b929e] uppercase">Altitude</label>
              <select value={alt} onChange={(e: any) => { setAlt(e.target.value); setTraceData(null); }} className="bg-white text-xs text-[#1a1d23] border border-slate-200 rounded p-1 outline-none">
                <option value="service">Service</option>
                <option value="code">Code (Crossings)</option>
              </select>
            </div>

            <div>
              <div className="flex justify-between text-2xs font-semibold text-[#8b929e] uppercase mb-1">
                <span>Min Confidence</span> <span className="text-[#315b47]">{(minConf*100).toFixed(0)}%</span>
              </div>
              <input type="range" min="0.6" max="1.0" step="0.05" value={minConf} onChange={e => { setMinConf(parseFloat(e.target.value)); setTraceData(null); }} className="w-full h-1 bg-slate-200 rounded-lg appearance-none accent-[#315b47]" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8b929e] uppercase mb-1">
                  <span>Max Hops</span> <span className="text-[#315b47]">{maxHops}</span>
                </div>
                <input type="range" min="1" max="8" step="1" value={maxHops} onChange={e => { setMaxHops(parseInt(e.target.value)); setTraceData(null); }} className="w-full h-1 bg-slate-200 rounded-lg appearance-none accent-[#315b47]" />
              </div>
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8b929e] uppercase mb-1">
                  <span>Max Paths (k)</span> <span className="text-[#315b47]">{k}</span>
                </div>
                <input type="range" min="1" max="5" step="1" value={k} onChange={e => { setK(parseInt(e.target.value)); setTraceData(null); }} className="w-full h-1 bg-slate-200 rounded-lg appearance-none accent-[#315b47]" />
              </div>
            </div>
          </div>

          <button
            onClick={() => onTrace(fromSvc, toSvc, minConf, alt, maxHops, k)}
            disabled={!fromSvc || !toSvc || sameEndpoint || tracing}
            className="w-full mt-2 bg-[#315b47] hover:bg-[#274a3a] disabled:bg-[#8a8e84] disabled:opacity-50 text-white font-medium py-2 rounded-lg flex items-center justify-center gap-2 transition-colors"
          >
            {tracing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Trace Paths
          </button>
          {sameEndpoint && (
            <p className="text-center text-2xs text-[#6f5723]">Choose two different services.</p>
          )}
        </div>

        {traceError?.error === "service_not_found" && (
          <div className="bg-red-50 border border-red-200 p-3 rounded-lg mt-4">
            <p className="text-xs text-red-600 font-semibold mb-2">Service not found.</p>
            {traceError.suggestions && traceError.suggestions.length > 0 && (
              <div>
                <p className="text-2xs text-red-500 mb-1">Did you mean:</p>
                <div className="flex flex-wrap gap-1">
                  {traceError.suggestions.map((s: string) => (
                    <button key={s} onClick={() => setFromSvc(s)} className="text-2xs bg-red-50 px-1.5 py-0.5 rounded text-red-600 hover:bg-red-100 transition-colors border border-red-200">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {traceData && traceData.paths && (
          <div className="space-y-3">
            <h4 className="text-xs font-semibold text-[#1a1d23] flex items-center gap-1.5">
              <GitMerge className="w-3.5 h-3.5 text-[#9b7a31]" />
              Discovered Paths ({traceData.paths.length})
            </h4>
            {traceData.paths.length === 0 ? (
              <p className="text-xs text-[#8b929e]">No paths found matching constraints.</p>
            ) : (
              traceData.paths.map((p, idx) => (
                <div key={idx} className="bg-slate-50 border border-slate-200 p-3 rounded-xl">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-2xs font-semibold text-[#5c6370] uppercase">Path #{idx + 1}</span>
                    <span className="text-2xs bg-[#315b47]/10 text-[#274a3a] px-1.5 py-0.5 rounded border border-[#315b47]/25 font-mono">
                      {(p.min_confidence * 100).toFixed(1)}% conf
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1 text-2xs text-[#1a1d23]">
                    {p.nodes.map((n, i) => {
                      const outside = scopeRepoIds.length > 0 &&
                        !serviceIds.has(n.id);
                      return (
                        <span key={i} className="flex items-center gap-1">
                          <span
                            title={outside ? "Outside the selected repositories" : undefined}
                            className={`px-1.5 py-0.5 rounded truncate max-w-[100px] ${
                              outside
                                ? "bg-amber-50 text-amber-700 border border-amber-200"
                                : "bg-slate-200"}`}>
                            {n.name}
                          </span>
                          {i < p.nodes.length - 1 && <span className="text-[#8b929e]">→</span>}
                        </span>
                      );
                    })}
                  </div>
                  <div className="mt-2 space-y-1 border-t border-slate-200 pt-2">
                    {p.edges.map((edge, edgeIndex) => {
                      const source = p.nodes[edgeIndex];
                      const target = p.nodes[edgeIndex + 1];
                      if (!source || !target) return null;
                      return (
                        <button key={`${source.id}->${target.id}->${edge.type}`}
                          onClick={() => setSelectedEdge({
                            ...edge, source, target, crossings: p.crossings,
                            id: `${source.id}->${target.id}->${edge.type}`,
                          })}
                          className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1
                                     text-left text-2xs text-[#315b47] hover:bg-[#315b47]/10">
                          <span className="truncate">Inspect {source.name} → {target.name}</span>
                          <span className="shrink-0 font-mono">{edge.type}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
