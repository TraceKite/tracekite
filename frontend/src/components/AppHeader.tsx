import { useState, useEffect } from "react";
import {
  GitBranch, Plus, ChevronDown, RefreshCw, Layers,
  Github, Trash2, Loader2, Network, Zap
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import RepoPickerModal from "@/components/RepoPickerModal";
import GraphSearch from "@/components/GraphSearch";
import { api } from "@/lib/api";
import type { RepoSummary } from "@/lib/types";

export default function AppHeader() {
  const {
    repos, selectedRepo, setSelectedRepo, scopeRepoIds,
    setIngestionJob, setRepos, appMode, setAppMode,
    clientConfig, setClientConfig
  } = useGraphStore();

  const [githubUrl, setGithubUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [showIngest, setShowIngest] = useState(false);
  const [ingesting, setIngesting] = useState(false);

  // Operator limits come from the API so a deployment can change them without
  // a frontend rebuild.
  useEffect(() => {
    if (clientConfig) return;
    api.getClientConfig().then(setClientConfig).catch(() => {});
  }, [clientConfig, setClientConfig]);

  const repoButtonLabel = appMode === "repo"
    ? (selectedRepo ? `${selectedRepo.owner}/${selectedRepo.repo}` : "Select repo…")
    : scopeRepoIds.length === 0
      ? `All ${repos.length} repos`
      : scopeRepoIds.length === 1
        ? repos.find((r) => r.id === scopeRepoIds[0])?.repo ?? "1 repo"
        : `${scopeRepoIds.length} repos`;

  useEffect(() => {
    const handler = (e: Event) => {
      const url = (e as CustomEvent).detail;
      if (typeof url === "string") { setGithubUrl(url); setShowIngest(true); }
    };
    window.addEventListener("set-example-repo", handler);
    return () => window.removeEventListener("set-example-repo", handler);
  }, []);

  const handleIngest = async () => {
    if (!githubUrl.trim()) return;
    setIngesting(true);
    try {
      const result = await api.ingestRepo({
        github_url: githubUrl.trim(),
        branch: branch || undefined,
      });
      setIngestionJob({
        job_id: result.job_id,
        repo_id: result.repo_id,
        status: "queued",
        progress: 0,
        message: result.message,
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
      setGithubUrl("");
      setBranch("");
    } catch (err: any) {
      useGraphStore.getState().setError(err.message);
    } finally {
      setIngesting(false);
      setShowIngest(false);
    }
  };

  const handleRefresh = async () => {
    if (!selectedRepo) return;
    try {
      const result = await api.refreshRepo(selectedRepo.id);
      setIngestionJob({
        job_id: result.job_id,
        repo_id: result.repo_id,
        status: "queued",
        progress: 0,
        message: "Refresh queued",
        error: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      });
    } catch (err: any) {
      useGraphStore.getState().setError(err.message);
    }
  };

  const handleDelete = async () => {
    if (!selectedRepo) return;
    if (!confirm(`Delete ${selectedRepo.name}? This cannot be undone.`)) return;
    try {
      await api.deleteRepo(selectedRepo.id);
      setSelectedRepo(null);
      const updated = await api.listRepos();
      setRepos(updated.repos);
    } catch (err: any) {
      useGraphStore.getState().setError(err.message);
    }
  };

  return (
    <header className="h-14 flex items-center px-4 gap-3 z-20 flex-shrink-0"
      style={{ background: "rgba(17,24,39,0.8)", backdropFilter: "blur(12px)", borderBottom: "1px solid #2b313a" }}>

      <div className="flex items-center gap-2 flex-shrink-0">
        <div className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: "linear-gradient(135deg, #3b82f6, #8b5cf6)" }}>
          <Github className="w-4 h-4 text-white" />
        </div>
        <h1 className="text-sm font-bold text-[#e9ecef] hidden md:block">Adduce</h1>
      </div>

      <div className="w-px h-6 bg-[#2b313a] mx-2" />

      <div className="flex items-center gap-1 bg-[#15181c]/50 p-1 rounded-lg border border-[#2b313a] flex-shrink-0">
        <button onClick={() => setAppMode("repo")} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${appMode === "repo" ? "bg-blue-500/20 text-blue-400" : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5"}`}>
          <Github className="w-3.5 h-3.5" /> Repo
        </button>
        <button onClick={() => setAppMode("service_map")} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${appMode === "service_map" ? "bg-emerald-500/20 text-emerald-400" : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5"}`}>
          <Network className="w-3.5 h-3.5" /> Service Map
        </button>
        <button onClick={() => setAppMode("trace")} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${appMode === "trace" ? "bg-violet-500/20 text-violet-400" : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5"}`}>
          <Zap className="w-3.5 h-3.5" /> Trace
        </button>
      </div>

      <div className="w-px h-6 bg-[#2b313a] mx-2" />

      {/* Ingest collapses behind its own button. It is a once-per-repository
          setup action, and as an always-open URL + branch + button row it
          claimed the widest slot in a header used every session -- crowding
          the picker and the search out of legibility. */}
      <div className="relative flex-shrink-0">
        <button
          onClick={() => setShowIngest(!showIngest)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium
                     transition-colors bg-blue-600 hover:bg-blue-500 text-white"
        >
          {ingesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline">Ingest</span>
        </button>
        {showIngest && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setShowIngest(false)} />
            <div className="absolute top-full left-0 mt-1 z-50 w-80 rounded-lg p-3 space-y-2
                            bg-[#15181c] border border-[#2b313a] shadow-2xl"
                 style={{ animation: "fadeIn 0.15s ease-out" }}>
              <label className="block text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">
                Ingest a repository
              </label>
              <input
                type="url"
                autoFocus
                placeholder="https://github.com/owner/repo"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleIngest()}
                className="w-full text-sm px-3 py-1.5 rounded-lg bg-black/20 border border-white/5
                           text-[#e9ecef] outline-none focus:border-blue-500/50"
              />
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="branch (optional)"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="flex-1 text-sm px-3 py-1.5 rounded-lg bg-black/20 border border-white/5
                             text-[#e9ecef] outline-none focus:border-blue-500/50"
                />
                <button
                  onClick={handleIngest}
                  disabled={!githubUrl.trim() || ingesting}
                  className="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
                             bg-blue-600 hover:bg-blue-500 text-white
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Ingest
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* One repo button in one slot, whatever the view. The Repo tab picks a
          single codebase to render the internals of; Service Map and Trace
          share a multi-repo scope. Same modal, same search, different arity —
          consistent to use without pretending the views are alike. */}
      <div className="w-px h-6 bg-[#2b313a]" />
      <button
        onClick={() => setShowPicker(true)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm min-w-[190px]
                   hover:bg-white/5 transition-colors border border-white/5 bg-black/20"
      >
        {appMode === "repo"
          ? <GitBranch className="w-3.5 h-3.5 text-blue-400" />
          : <Layers className="w-3.5 h-3.5 text-emerald-400" />}
        <span className="flex-1 text-left truncate text-[#e9ecef]">{repoButtonLabel}</span>
        <ChevronDown className="w-3.5 h-3.5 text-[#8c949e]" />
      </button>
      {showPicker && (
        <RepoPickerModal
          mode="multi"
          onClose={() => setShowPicker(false)}
        />
      )}

      {/* Node search sits beside the repo picker rather than floating over the
          canvas. Placed there it was read as a SECOND repo selector -- its
          placeholder said "Select a repository first" -- so it now says what
          it does and lives next to the control it was confused with. */}
      {appMode === "repo" && (
        <div className="flex-1 min-w-[10rem] max-w-sm hidden lg:block">
          <GraphSearch />
        </div>
      )}

      {appMode === "repo" && (
        <>
          {selectedRepo && (
            <div className="flex items-center gap-1">
              <button onClick={handleRefresh} title="Refresh repository"
                className="p-1.5 rounded-lg hover:bg-white/10 text-[#8c949e] hover:text-[#e9ecef] transition-colors">
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              <button onClick={handleDelete} title="Delete repository"
                className="p-1.5 rounded-lg hover:bg-red-500/20 text-[#8c949e] hover:text-red-400 transition-colors">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </>
      )}
    </header>
  );
}