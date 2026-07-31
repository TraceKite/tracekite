import { useGraphStore } from "@/store/graphStore";
import { CircleDot, GitBranch, Layers, Globe, Package, Database, Boxes } from "lucide-react";

export default function RepoStats() {
  const { stats, selectedRepo } = useGraphStore();
  if (!stats || !selectedRepo) return null;

  const statCards = [
    { label: "Nodes", value: stats.total_nodes, icon: <CircleDot className="w-3.5 h-3.5" />, color: "#60a5fa" },
    { label: "Edges", value: stats.total_edges, icon: <GitBranch className="w-3.5 h-3.5" />, color: "#4ade80" },
    { label: "Files", value: stats.files, icon: <Layers className="w-3.5 h-3.5" />, color: "#aab2bb" },
    { label: "APIs", value: stats.apis, icon: <Globe className="w-3.5 h-3.5" />, color: "#f87171" },
    { label: "Deps", value: stats.dependencies, icon: <Package className="w-3.5 h-3.5" />, color: "#facc15" },
    { label: "Systems", value: stats.external_systems, icon: <Database className="w-3.5 h-3.5" />, color: "#f43f5e" },
  ];

  const sortedNodeTypes = Object.entries(stats.node_types).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const sortedEdgeTypes = Object.entries(stats.edge_types).sort((a, b) => b[1] - a[1]).slice(0, 5);

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider flex items-center gap-1.5 mb-3">
          <Boxes className="w-3 h-3" /> Statistics
        </h4>
        <div className="grid grid-cols-2 gap-2">
          {statCards.map((card) => (
            <div key={card.label} className="rounded-lg p-2 text-center bg-black/20 border border-white/5">
              <div className="flex justify-center mb-1" style={{ color: card.color }}>{card.icon}</div>
              <p className="text-lg font-bold text-[#e9ecef] leading-tight">{card.value.toLocaleString()}</p>
              <p className="text-2xs text-[#8c949e]">{card.label}</p>
            </div>
          ))}
        </div>
      </div>

      {selectedRepo.claims_by_kind && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">Claims</p>
          <div className="bg-black/20 border border-white/5 rounded-lg p-2 space-y-1">
            {Object.keys(selectedRepo.claims_by_kind).length === 0 ? (
              <p className="text-xs text-[#8c949e] text-center">No claims</p>
            ) : (
              Object.entries(selectedRepo.claims_by_kind).map(([kind, count]) => (
                <div key={kind} className="flex items-center justify-between text-xs">
                  <span className="text-[#aab2bb]">{kind}</span>
                  <span className="text-[#8c949e] bg-[#2b313a] px-1.5 py-0.5 rounded">{count}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {selectedRepo.parse_coverage && Object.keys(selectedRepo.parse_coverage).length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">Parse Coverage</p>
          <div className="bg-black/20 border border-white/5 rounded-lg p-2 space-y-2">
            {Object.entries(selectedRepo.parse_coverage).map(([lang, cov]) => {
              const pct = cov.files_seen > 0 ? ((cov.files_parsed / cov.files_seen) * 100).toFixed(0) : 0;
              const isFull = cov.tier === "full";
              return (
                <div key={lang} className="text-xs space-y-1">
                  <div className="flex justify-between items-center text-[#e9ecef]">
                    <span className="flex items-center gap-1.5">
                      {lang}
                      <span className={`text-2xs px-1.5 py-0.5 rounded ${isFull ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                        {cov.tier}
                      </span>
                    </span>
                    <span className="text-[#8c949e]">{pct}%</span>
                  </div>
                  <div className="w-full h-1 bg-[#2b313a] rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: isFull ? "#10b981" : "#f59e0b" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {sortedNodeTypes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">Node Types</p>
          {sortedNodeTypes.map(([type, count]) => (
            <div key={type} className="flex items-center justify-between text-xs">
              <span className="text-[#e9ecef]">{type}</span>
              <span className="text-[#8c949e]">{count}</span>
            </div>
          ))}
        </div>
      )}

      {sortedEdgeTypes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">Edge Types</p>
          {sortedEdgeTypes.map(([type, count]) => (
            <div key={type} className="flex items-center justify-between text-xs">
              <span className="text-[#e9ecef]">{type}</span>
              <span className="text-[#8c949e]">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}