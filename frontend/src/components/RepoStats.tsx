import { useGraphStore } from "@/store/graphStore";
import { CircleDot, GitBranch, Layers, Globe, Package, Database, Boxes } from "lucide-react";
import { summarizeCoverage } from "@/lib/coverageSummary";
import { effectiveRepoIds } from "@/lib/graphNavigation";

export default function RepoStats() {
  const { stats, repos, selectedRepo, scopeRepoIds } = useGraphStore();
  if (!stats || !selectedRepo) return null;
  const multiRepo = effectiveRepoIds(repos, scopeRepoIds, selectedRepo).length > 1;

  const statCards = [
    { label: "Loaded nodes", value: stats.total_nodes, icon: <CircleDot className="w-3.5 h-3.5" />, color: "#315b47" },
    { label: "Loaded edges", value: stats.total_edges, icon: <GitBranch className="w-3.5 h-3.5" />, color: "#a45138" },
    ...(!multiRepo ? [
      { label: "Sample files", value: stats.files, icon: <Layers className="w-3.5 h-3.5" />, color: "#6b6f65" },
      { label: "Sample APIs", value: stats.apis, icon: <Globe className="w-3.5 h-3.5" />, color: "#a45138" },
      { label: "Sample deps", value: stats.dependencies, icon: <Package className="w-3.5 h-3.5" />, color: "#9b7a31" },
      { label: "Sample systems", value: stats.external_systems, icon: <Database className="w-3.5 h-3.5" />, color: "#3c4038" },
    ] : []),
  ];

  const sortedNodeTypes = Object.entries(stats.node_types).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const sortedEdgeTypes = Object.entries(stats.edge_types).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const coverage = selectedRepo.parse_coverage
    ? summarizeCoverage(selectedRepo.parse_coverage)
    : null;

  return (
    <div className="space-y-3.5">
      <div>
        <h4 className="text-2xs font-semibold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 mb-2.5">
          <Boxes className="w-3 h-3" /> Statistics
        </h4>
        <div className="grid grid-cols-2 gap-2">
          {statCards.map((card) => (
            <div key={card.label} className="rounded-xl p-2.5 text-center bg-slate-50/80 border border-slate-200 shadow-xs">
              <div className="flex justify-center mb-1" style={{ color: card.color }}>{card.icon}</div>
              <p className="text-base font-bold text-slate-900 leading-tight">{card.value.toLocaleString()}</p>
              <p className="text-2xs font-medium text-slate-400">{card.label}</p>
            </div>
          ))}
        </div>
      </div>

      {!multiRepo && selectedRepo.claims_by_kind && Object.keys(selectedRepo.claims_by_kind).length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">Claims</p>
          <div className="bg-slate-50/80 border border-slate-200 rounded-xl p-2.5 space-y-1 shadow-xs">
            {Object.entries(selectedRepo.claims_by_kind).map(([kind, count]) => (
              <div key={kind} className="flex items-center justify-between text-xs">
                <span className="text-slate-600 font-mono text-2xs truncate max-w-[170px]">{kind}</span>
                <span className="text-slate-500 bg-white border border-slate-200 px-1.5 py-0.5 rounded font-mono text-2xs">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!multiRepo && coverage && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">Extraction Coverage</p>
          <div className="bg-slate-50/80 border border-slate-200 rounded-xl p-2.5 space-y-2 shadow-xs">
            {coverage.percentage == null ? (
              <p className="text-2xs leading-relaxed text-slate-500">
                File coverage totals were not recorded for this ingestion.
              </p>
            ) : (
              <>
                <div className="flex justify-between text-xs text-slate-700">
                  <span>{coverage.filesParsed} of {coverage.filesSeen} files parsed</span>
                  <span className="font-mono">{coverage.percentage}%</span>
                </div>
                <div className="h-1 overflow-hidden rounded-full bg-slate-200">
                  <div className="h-full rounded-full bg-[#315b47]"
                       style={{ width: `${coverage.percentage}%` }} />
                </div>
              </>
            )}
            {coverage.counters.slice(0, 6).map((counter) => (
              <div key={counter.label} className="flex justify-between text-2xs">
                <span className="text-slate-600">{counter.label}</span>
                <span className="font-mono text-slate-500">{counter.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sortedNodeTypes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">Node Types</p>
          <div className="bg-slate-50/80 border border-slate-200 rounded-xl p-2.5 space-y-1 shadow-xs">
            {sortedNodeTypes.map(([type, count]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span className="text-slate-700">{type}</span>
                <span className="text-slate-400 font-mono text-2xs">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {sortedEdgeTypes.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">Edge Types</p>
          <div className="bg-slate-50/80 border border-slate-200 rounded-xl p-2.5 space-y-1 shadow-xs">
            {sortedEdgeTypes.map(([type, count]) => (
              <div key={type} className="flex items-center justify-between text-xs">
                <span className="text-slate-700">{type}</span>
                <span className="text-slate-400 font-mono text-2xs">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
