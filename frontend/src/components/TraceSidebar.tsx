import { useMemo, useState } from "react";
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
  const { traceData, serviceMapData, scopeRepoIds, traceFrom, traceTo, setTraceEndpoints } =
    useGraphStore();
  const fromSvc = traceFrom;
  const toSvc = traceTo;
  const setFromSvc = (v: string) => setTraceEndpoints(v, traceTo);
  const setToSvc = (v: string) => setTraceEndpoints(traceFrom, v);
  const [minConf, setMinConf] = useState(0.6);
  const [alt, setAlt] = useState<"service" | "code">("service");
  const [maxHops, setMaxHops] = useState(6);
  const [k, setK] = useState(3);

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

  return (
    <aside className="w-80 flex-shrink-0 border-r border-[#2b313a] bg-[#15181c] flex flex-col overflow-hidden z-10 shadow-2xl">
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <h3 className="text-lg font-bold text-[#e9ecef] flex items-center gap-2 mb-1">
            <Zap className="w-5 h-5 text-violet-400" /> Distributed Trace
          </h3>
          <p className="text-xs text-[#e9ecef] font-medium">How does A reach B, and through which hops?</p>
          <p className="text-2xs text-[#8c949e] mt-1 leading-relaxed">
            One journey, not the whole estate. Ranked paths laid out in hop
            order, every hop backed by a file and line.
          </p>
        </div>

        <div className="space-y-4 bg-black/20 p-4 rounded-xl border border-white/5">
          <div>
            <label className="text-xs font-semibold text-[#aab2bb] block mb-1">Origin Service</label>
            <button
              onClick={() => setPickerTarget("from")}
              className="w-full flex items-center justify-between bg-[#2b313a] border border-white/10 hover:border-violet-500/50 rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={fromSvc ? "text-white font-medium" : "text-[#8c949e]"}>
                {fromSvc
                  ? serviceLabel(fromSvc)
                  : (services[0] ? `e.g. ${services[0].name}` : "Select origin service…")}
              </span>
              <span className="text-2xs text-violet-400 font-semibold uppercase shrink-0">Choose</span>
            </button>
          </div>

          <div>
            <label className="text-xs font-semibold text-[#aab2bb] block mb-1">Destination Service</label>
            <button
              onClick={() => setPickerTarget("to")}
              className="w-full flex items-center justify-between bg-[#2b313a] border border-white/10 hover:border-violet-500/50 rounded-lg px-3 py-2 text-sm text-left transition-colors"
            >
              <span className={toSvc ? "text-white font-medium" : "text-[#8c949e]"}>
                {toSvc
                  ? serviceLabel(toSvc)
                  : (services[1] ? `e.g. ${services[1].name}` : "Select destination service…")}
              </span>
              <span className="text-2xs text-violet-400 font-semibold uppercase shrink-0">Choose</span>
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
              onClose={() => setPickerTarget(null)}
            />
          )}

          <div className="pt-2 border-t border-white/5 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-2xs font-semibold text-[#8c949e] uppercase">Altitude</label>
              <select value={alt} onChange={(e: any) => setAlt(e.target.value)} className="bg-[#2b313a] text-xs text-white border border-white/10 rounded p-1 outline-none">
                <option value="service">Service</option>
                <option value="code">Code (Crossings)</option>
              </select>
            </div>

            <div>
              <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                <span>Min Confidence</span> <span className="text-violet-400">{(minConf*100).toFixed(0)}%</span>
              </div>
              <input type="range" min="0.6" max="1.0" step="0.05" value={minConf} onChange={e => setMinConf(parseFloat(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                  <span>Max Hops</span> <span className="text-violet-400">{maxHops}</span>
                </div>
                <input type="range" min="1" max="8" step="1" value={maxHops} onChange={e => setMaxHops(parseInt(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
              </div>
              <div>
                <div className="flex justify-between text-2xs font-semibold text-[#8c949e] uppercase mb-1">
                  <span>Max Paths (k)</span> <span className="text-violet-400">{k}</span>
                </div>
                <input type="range" min="1" max="5" step="1" value={k} onChange={e => setK(parseInt(e.target.value))} className="w-full h-1 bg-[#2b313a] rounded-lg appearance-none accent-violet-500" />
              </div>
            </div>
          </div>

          <button
            onClick={() => onTrace(fromSvc, toSvc, minConf, alt, maxHops, k)}
            disabled={!fromSvc || !toSvc || tracing}
            className="w-full mt-2 bg-violet-600 hover:bg-violet-500 disabled:bg-violet-900 disabled:opacity-50 text-white font-medium py-2 rounded-lg flex items-center justify-center gap-2 transition-colors"
          >
            {tracing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Trace Paths
          </button>
        </div>

        {traceError?.error === "service_not_found" && (
          <div className="bg-red-500/10 border border-red-500/20 p-3 rounded-lg mt-4">
            <p className="text-xs text-red-400 font-semibold mb-2">Service not found.</p>
            {traceError.suggestions && traceError.suggestions.length > 0 && (
              <div>
                <p className="text-2xs text-red-300/70 mb-1">Did you mean:</p>
                <div className="flex flex-wrap gap-1">
                  {traceError.suggestions.map((s: string) => (
                    <button key={s} onClick={() => setFromSvc(s)} className="text-2xs bg-red-500/20 px-1.5 py-0.5 rounded text-red-300 hover:bg-red-500/30 transition-colors">
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
            <h4 className="text-xs font-semibold text-[#e9ecef] flex items-center gap-1.5">
              <GitMerge className="w-3.5 h-3.5 text-violet-400" />
              Discovered Paths ({traceData.paths.length})
            </h4>
            {traceData.paths.length === 0 ? (
              <p className="text-xs text-[#8c949e]">No paths found matching constraints.</p>
            ) : (
              traceData.paths.map((p, idx) => (
                <div key={idx} className="bg-[#2b313a]/50 border border-white/5 p-3 rounded-xl hover:bg-[#2b313a] transition-colors cursor-pointer group">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-2xs font-semibold text-[#aab2bb] uppercase">Path #{idx + 1}</span>
                    <span className="text-2xs bg-black/40 text-violet-300 px-1.5 py-0.5 rounded border border-white/5 font-mono">
                      {(p.min_confidence * 100).toFixed(1)}% conf
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-1 text-2xs text-[#e9ecef]">
                    {p.nodes.map((n, i) => {
                      // A hop outside the selected repos is shown, not hidden:
                      // the path is real and suppressing it would misreport
                      // reachability. Flag it so the detour is obvious.
                      const outside = scopeRepoIds.length > 0 &&
                        !serviceIds.has(n.id);
                      return (
                        <span key={i} className="flex items-center gap-1">
                          <span
                            title={outside ? "Outside the selected repositories" : undefined}
                            className={`px-1.5 py-0.5 rounded truncate max-w-[100px] ${
                              outside
                                ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                : "bg-black/30"}`}>
                            {n.name}
                          </span>
                          {i < p.nodes.length - 1 && <span className="text-[#8c949e]">→</span>}
                        </span>
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
