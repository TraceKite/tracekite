/** The repository picker — one component, used by all three views.
 *
 * `mode="single"` is the Repo tab, which renders one codebase's internals and
 * is therefore genuinely singular; `mode="multi"` is the scope shared by
 * Service Map and Trace. Same modal, same search, same rows — only the arity
 * differs, which is honest about the views without making them look unrelated.
 *
 * Search rather than pagination: you almost always know the repo's name, and
 * paging makes you hunt for the page it happens to be on.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, AlertTriangle } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import type { RepoSummary } from "@/lib/types";

interface Props {
  mode: "single" | "multi";
  onClose: () => void;
}

export default function RepoPickerModal({ mode, onClose }: Props) {
  const {
    repos, scopeRepoIds, setScopeRepos, selectedRepo, setSelectedRepo,
    serviceMapData, clientConfig,
  } = useGraphStore();
  const [query, setQuery] = useState("");
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
    const ids = scopeRepoIds;
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
  }, [serviceMapData, scopeRepoIds]);

  const atCap = mode === "multi" && scopeRepoIds.length >= maxRepos;

  const toggle = (repo: RepoSummary) => {
    if (mode === "single") {
      setSelectedRepo(repo);
      onClose();
      return;
    }
    const on = scopeRepoIds.includes(repo.id);
    if (on) {
      setScopeRepos(scopeRepoIds.filter((id) => id !== repo.id));
    } else if (!atCap) {
      setScopeRepos([...scopeRepoIds, repo.id]);
    }
  };

  const isOn = (repo: RepoSummary) =>
    mode === "single"
      ? selectedRepo?.id === repo.id
      : scopeRepoIds.length === 0 || scopeRepoIds.includes(repo.id);

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={mode === "single" ? "Choose a repository" : "Repositories in scope"}
        className="fixed left-1/2 top-24 z-50 w-[min(92vw,34rem)] -translate-x-1/2 rounded-xl
                   bg-[#15181c] border border-[#2b313a] shadow-2xl overflow-hidden"
        style={{ animation: "fadeIn 0.15s ease-out" }}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2b313a]">
          <div>
            <h2 className="text-sm font-bold text-[#e9ecef]">
              {mode === "single" ? "Choose a repository" : "Repositories in scope"}
            </h2>
            <p className="text-2xs text-[#8c949e] mt-0.5">
              {mode === "single"
                ? "The Repo view renders one codebase's internals."
                : `Service Map and Trace both obey this. Up to ${maxRepos} at once.`}
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="text-[#8c949e] hover:text-white p-1"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-4 py-2 border-b border-[#2b313a]">
          <div className="flex items-center gap-2 bg-black/30 rounded-lg px-2.5 py-1.5
                          border border-white/5 focus-within:border-emerald-500/50">
            <Search className="w-3.5 h-3.5 text-[#8c949e] shrink-0" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter repositories…"
              className="flex-1 bg-transparent text-sm text-[#e9ecef] outline-none
                         placeholder:text-[#5c636d]"
            />
          </div>
        </div>

        <div className="max-h-[45vh] overflow-y-auto py-1">
          {filtered.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-[#8c949e]">
              No repository matches “{query}”.
            </p>
          )}
          {filtered.map((repo) => {
            const on = isOn(repo);
            // Only a genuine off-state blocks; an implicit "all" must stay
            // clickable or the cap would freeze the picker on first open.
            const blocked = mode === "multi" && atCap && !scopeRepoIds.includes(repo.id);
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
                           hover:bg-white/5 disabled:cursor-not-allowed"
                style={{ opacity: blocked ? 0.35 : on ? 1 : 0.55 }}
              >
                <span className={`w-3.5 h-3.5 shrink-0 border ${
                  mode === "single" ? "rounded-full" : "rounded-sm"} ${
                  on ? "bg-emerald-500/80 border-emerald-400" : "border-white/25"}`} />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs text-[#e9ecef] truncate">{repo.repo}</span>
                  <span className="block text-2xs text-[#8c949e] truncate">{repo.owner}</span>
                </span>
                <span className="text-2xs text-[#8c949e] font-mono shrink-0">{count}</span>
              </button>
            );
          })}
        </div>

        {mode === "multi" && (
          <div className="px-4 py-3 border-t border-[#2b313a] space-y-2">
            <div className="flex items-center justify-between text-2xs">
              <span className="text-[#8c949e]">
                {scopeRepoIds.length === 0
                  ? `All ${repos.length} repos`
                  : `${scopeRepoIds.length} of ${maxRepos} selected`}
                {cost && ` · ${cost.services} services · ${cost.links} links`}
              </span>
              {scopeRepoIds.length > 0 && (
                <button onClick={() => setScopeRepos([])}
                        className="text-[#8c949e] hover:text-[#e9ecef]">Select all</button>
              )}
            </div>
            {cost && cost.links >= edgeLimit && (
              <p className="flex items-start gap-1.5 text-2xs text-amber-300">
                <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                At {edgeLimit} links the service map truncates — narrow the scope
                to be sure you are seeing everything.
              </p>
            )}
          </div>
        )}
      </div>
    </>
  );
}
