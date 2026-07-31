import { useGraphStore } from "@/store/graphStore";
import { X, Copy, ExternalLink, Network, CheckCircle2 } from "lucide-react";
import { formatConfidence, getConfidenceColor } from "@/lib/graphStyle";

export default function EdgeDetailsDrawer() {
  const { selectedEdge, setSelectedEdge, repos, serviceMapData } = useGraphStore();

  if (!selectedEdge) return null;

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const getSourceNode = () => {
    const sourceId = typeof selectedEdge.source === 'object' ? selectedEdge.source.id : selectedEdge.source;
    return serviceMapData?.nodes.find(n => n.id === sourceId);
  };

  const evidenceLinks = () => {
    if (!selectedEdge.evidence || selectedEdge.evidence.length === 0) return null;
    const sourceNode = getSourceNode();
    // The edge names the repo its evidence resolves in. repo_ids[0] is an
    // arbitrary pick when a service exists in several repos — both petclinic
    // repos ship a spring-petclinic-api-gateway/ module, so the deep link
    // opened the WRONG repo's file at the right path.
    const defaultRepoId = (selectedEdge as any).source_repo_id || sourceNode?.repo_ids?.[0];

    return (
      <div className="space-y-1.5 pt-2 border-t border-white/5">
        <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2">Evidence ({selectedEdge.evidence.length})</h4>
        <div className="space-y-1.5">
          {selectedEdge.evidence.map((ev: string, idx: number) => {
            const lastColon = ev.lastIndexOf(":");
            if (lastColon === -1) {
              return <div key={idx} className="text-2xs text-[#aab2bb] font-mono break-all bg-black/20 p-1.5 rounded">{ev}</div>;
            }
            const path = ev.substring(0, lastColon);
            const line = ev.substring(lastColon + 1);
            
            let repoId = defaultRepoId;
            const crossing = selectedEdge.crossings?.find((c: any) => c.evidence.includes(ev));
            if (crossing) {
              repoId = crossing.call_site.split(":")[0];
            }

            const repo = repos.find(r => r.id === repoId);
            if (repo && repo.head_commit_sha) {
              const url = `${repo.github_url}/blob/${repo.head_commit_sha}/${path}#L${line}`;
              return (
                <a key={idx} href={url} target="_blank" rel="noreferrer" 
                   className="flex items-center justify-between text-2xs text-blue-400 hover:text-blue-300 font-mono truncate bg-blue-500/10 hover:bg-blue-500/20 p-2 rounded transition-colors group">
                  <span className="truncate">{repoId ? `${repoId.split("_").pop()}/` : ""}{path}:{line}</span>
                  <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 flex-shrink-0 ml-2" />
                </a>
              );
            }
            return <div key={idx} className="text-2xs text-[#aab2bb] font-mono truncate bg-black/20 border border-white/5 p-2 rounded">{repoId ? `${repoId.split("_").pop()}/` : ""}{path}:{line}</div>;
          })}
        </div>
      </div>
    );
  };

  const sourceName = typeof selectedEdge.source === 'object' ? selectedEdge.source.name || selectedEdge.source.label : selectedEdge.source;
  const targetName = typeof selectedEdge.target === 'object' ? selectedEdge.target.name || selectedEdge.target.label : selectedEdge.target;

  return (
    <aside className="w-80 flex-shrink-0 flex flex-col overflow-hidden bg-[#15181c] border-l border-[#2b313a] z-20" style={{ animation: "fadeIn 0.2s ease-out" }}>
      <div className="p-4 flex-shrink-0 border-b border-[#2b313a]">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center flex-shrink-0">
              <Network className="w-4 h-4 text-blue-400" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[#e9ecef] truncate">{selectedEdge.type}</h3>
              <p className="text-2xs text-[#8c949e] truncate mt-0.5">{sourceName} → {targetName}</p>
            </div>
          </div>
          <button onClick={() => setSelectedEdge(null)} className="text-[#8c949e] hover:text-[#e9ecef] transition-colors flex-shrink-0 p-1">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        <div className="bg-[#2b313a]/50 p-3 rounded-xl border border-white/5 space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs font-semibold text-[#aab2bb]">Confidence</span>
            <span className="text-sm font-bold bg-black/30 px-2 py-0.5 rounded border border-white/5" style={{ color: getConfidenceColor(selectedEdge.confidence) }}>
              {formatConfidence(selectedEdge.confidence)}
            </span>
          </div>
          {(selectedEdge.min_confidence !== undefined || selectedEdge.max_confidence !== undefined) && (
            <div className="flex justify-between items-center">
              <span className="text-xs font-semibold text-[#aab2bb]">Range</span>
              <span className="text-xs text-[#aab2bb]">
                {formatConfidence(selectedEdge.min_confidence)} – {formatConfidence(selectedEdge.max_confidence)}
              </span>
            </div>
          )}
          {selectedEdge.weight !== undefined && (
            <div className="flex justify-between items-center">
              <span className="text-xs font-semibold text-[#aab2bb]">Weight</span>
              <span className="text-xs text-[#aab2bb]">{selectedEdge.weight}</span>
            </div>
          )}
          {selectedEdge.path_prefix && (
            <div className="pt-2 border-t border-white/5">
              <span className="text-2xs font-semibold text-[#aab2bb] uppercase tracking-wider block mb-1">Path Prefix</span>
              <div className="text-xs text-emerald-400 font-mono bg-emerald-500/10 border border-emerald-500/20 p-2 rounded break-all">
                {selectedEdge.path_prefix}
              </div>
            </div>
          )}
        </div>

        {selectedEdge.via && selectedEdge.via.length > 0 && (
          <div>
            <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <CheckCircle2 className="w-3 h-3 text-emerald-500" /> Via Signals
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {selectedEdge.via.map((v: string) => (
                <span key={v} className="text-2xs text-[#aab2bb] bg-black/30 px-2 py-1 rounded-md border border-white/5">{v}</span>
              ))}
            </div>
          </div>
        )}

        {evidenceLinks()}

        {selectedEdge.crossings && selectedEdge.crossings.length > 0 && (
          <div className="space-y-1.5 pt-2 border-t border-white/5">
            <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2">Crossings ({selectedEdge.crossings.length})</h4>
            <div className="space-y-2">
              {selectedEdge.crossings.map((c: any, idx: number) => (
                <div key={idx} className="bg-black/20 border border-white/5 rounded-lg p-2 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-xs font-semibold text-violet-400 break-all">{c.method}</span>
                    <span className="text-2xs text-violet-300 bg-violet-500/10 px-1.5 py-0.5 rounded flex-shrink-0 border border-violet-500/20">
                      {formatConfidence(c.confidence)}
                    </span>
                  </div>
                  <div className="text-2xs text-[#aab2bb] font-mono break-all bg-black/40 p-1.5 rounded">{c.path_template}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}