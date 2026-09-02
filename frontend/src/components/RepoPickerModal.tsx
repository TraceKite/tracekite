/** One repository-scope control for Repo, Service Map and Trace. */

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, AlertTriangle } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import type { RepoSummary } from "@/lib/types";
import { toggleDraftRepoScope } from "@/lib/graphNavigation";

interface Props {
  mode: "repo" | "multi";
  onClose: () => void;
}

export default function RepoPickerModal({ mode, onClose }: Props) {
  const {
    repos, scopeRepoIds, setScopeRepos, selectedRepo, setSelectedRepo,
    serviceMapData, clientConfig,
  } = useGraphStore();
  const [query, setQuery] = useState("");
  const [draftIds, setDraftIds] = useState(scopeRepoIds);
  const searchRef = useRef<HTMLInputElement>(null);
  const maxRepos = clientConfig?.max_scope_repos ?? 10;
  const edgeLimit = clientConfig?.service_map_edge_limit ?? 500;

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return repos;
    return repos.filter((r) =>
      r.name.toLowerCase().includes(q) || r.repo.toLowerCase().includes(q));
  }, [repos, query]);

  /** Services and links the current selection would actually draw.
   *
   * The repo cap is a proxy — render cost is nodes and edges, and repo size
   * varies enormously. Showing the real numbers means the cheap rule prevents
   * accidents while the true cost stays visible. */
  const cost = useMemo(() => {
    if (!serviceMapData) return null;
    const ids = draftIds;
    const inScope = (n: any) =>
      ids.length === 0 || (n.repo_ids ?? []).some((id: string) => ids.includes(id));
    const services = serviceMapData.nodes.filter(
      (n: any) => n.kind === "service" && inScope(n)).length;
    const links = ids.length === 0
      ? serviceMapData.totals.edges
      : serviceMapData.edges.filter((e: any) => {
          const src: string = e.source_repo_id || "";
          return src ? ids.includes(src) : true;
        }).length;
    return { services, links };
  }, [draftIds, serviceMapData]);

  const atCap = draftIds.length >= maxRepos;
  const canSelectAll = repos.length <= maxRepos;

  const toggle = (repo: RepoSummary) => {
    setDraftIds(toggleDraftRepoScope(draftIds, repo.id, maxRepos));
  };

  const isOn = (repo: RepoSummary) => draftIds.includes(repo.id);
  const title = mode === "repo" ? "Repositories on graph" : "Repositories in scope";
  const apply = () => {
    setScopeRepos(draftIds);
    if (draftIds.length === 1 ||
        (draftIds.length > 1 && !draftIds.includes(selectedRepo?.id ?? ""))) {
      setSelectedRepo(repos.find((repo) => repo.id === draftIds[0]) ?? null);
    }
    onClose();
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/30" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed left-1/2 top-24 z-50 w-[min(92vw,34rem)] -translate-x-1/2 rounded-xl
                   bg-white border border-[#dfe2e8] shadow-sm overflow-hidden"
        style={{ animation: "fadeIn 0.15s ease-out" }}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#dfe2e8]">
          <div>
            <h2 className="text-sm font-bold text-[#1a1d23]">
              {title}
            </h2>
            <p className="text-2xs text-[#8b929e] mt-0.5">
              {`Choose, then Apply. This scope continues into every workspace; up to ${maxRepos} explicit repos.`}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="text-[#8b929e] hover:text-[#1a1d23] p-1"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-4 py-2 border-b border-[#dfe2e8]">
          <div className="flex items-center gap-2 bg-slate-50 rounded-lg px-2.5 py-1.5
                          border border-slate-200 focus-within:border-[#315b47]">
            <Search className="w-3.5 h-3.5 text-[#8b929e] shrink-0" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter repositories…"
              className="flex-1 bg-transparent text-sm text-[#1a1d23] outline-none
                         placeholder:text-[#9ca3af]"
            />
          </div>
        </div>

        <div className="max-h-[45vh] overflow-y-auto py-1">
          <button
            onClick={() => { if (canSelectAll) setDraftIds([]); }}
            disabled={!canSelectAll}
            aria-pressed={draftIds.length === 0}
            title={canSelectAll ? "Use every repository" :
              `${repos.length} repositories exceeds the ${maxRepos}-repository limit`}
            className="mb-1 flex w-full items-center gap-3 border-b border-[#dfe2e8]
                       px-4 py-2 text-left hover:bg-[#f4f1e9] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <span className={`h-3.5 w-3.5 shrink-0 rounded-sm border ${
              draftIds.length === 0
                ? "border-[#315b47] bg-[#315b47]"
                : "border-[#c9c3b7]"
            }`} />
            <span className="flex-1 text-xs font-semibold text-[#252821]">All repositories</span>
            <span className="font-mono text-2xs text-[#8b929e]">{repos.length}</span>
          </button>
          {filtered.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-[#8b929e]">
              No repository matches “{query}”.
            </p>
          )}
          {filtered.map((repo) => {
            const on = isOn(repo);
            const blocked = atCap && !draftIds.includes(repo.id);
            const count = serviceMapData?.nodes.filter(
              (n: any) => (n.repo_ids ?? []).includes(repo.id)).length ?? 0;
            return (
              <button
                key={repo.id}
                onClick={() => toggle(repo)}
                disabled={blocked}
                aria-pressed={on}
                title={blocked ? `Cap of ${maxRepos} reached — deselect one first` : repo.name}
                className="w-full flex items-center gap-3 px-4 py-2 text-left transition-colors
                           hover:bg-slate-50 disabled:cursor-not-allowed"
                style={{ opacity: blocked ? 0.35 : on ? 1 : 0.55 }}
              >
                <span className={`w-3.5 h-3.5 shrink-0 rounded-sm border ${
                  on ? "bg-[#315b47] border-[#315b47]" : "border-slate-300"}`} />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs text-[#1a1d23] truncate">{repo.repo}</span>
                  <span className="block text-2xs text-[#8b929e] truncate">{repo.owner}</span>
                </span>
                <span className="text-2xs text-[#8b929e] font-mono shrink-0">
                  {mode === "repo" ? repo.node_count : count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="px-4 py-3 border-t border-[#dfe2e8] space-y-2">
            <div className="flex items-center justify-between text-2xs">
              <span className="text-[#8b929e]">
                {draftIds.length === 0
                  ? `All ${repos.length} repos`
                  : `${draftIds.length} of ${maxRepos} selected`}
                {mode === "multi" && cost && ` · ${cost.services} services · ${cost.links} links`}
              </span>
              {draftIds.length > 0 && canSelectAll && (
                <button onClick={() => setDraftIds([])}
                        className="text-[#8b929e] hover:text-[#1a1d23]">Select all</button>
              )}
            </div>
            {!canSelectAll && (
              <p className="text-2xs text-[#6f5723]">
                All {repos.length} repositories exceeds the limit; choose up to {maxRepos}.
              </p>
            )}
            {mode === "multi" && cost && cost.links >= edgeLimit && (
              <p className="flex items-start gap-1.5 text-2xs text-amber-600">
                <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                At {edgeLimit} links the service map truncates — narrow the scope
                to be sure you are seeing everything.
              </p>
            )}
            <div className="flex justify-end gap-2 border-t border-[#dfe2e8] pt-2">
              <button onClick={onClose}
                      className="rounded-md px-3 py-1.5 text-xs text-[#6e7168] hover:bg-[#f4f1e9]">
                Cancel
              </button>
              <button onClick={apply}
                      disabled={draftIds.length === 0 && !canSelectAll}
                      className="rounded-md bg-[#315b47] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#274a3a] disabled:cursor-not-allowed disabled:opacity-45">
                Apply scope
              </button>
            </div>
        </div>
      </div>
    </>
  );
}
