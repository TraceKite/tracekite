import { useState, useEffect, useRef } from "react";
import {
  GitBranch, Plus, ChevronDown, RefreshCw, Layers,
  Trash2, Loader2, Box
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import RepoPickerModal from "@/components/RepoPickerModal";
import GraphSearch from "@/components/GraphSearch";
import { api } from "@/lib/api";
import { isPreviewMode } from "@/lib/previewFixtures";
import { effectiveRepoIds } from "@/lib/graphNavigation";
import WorkspaceNavigation from "@/components/WorkspaceNavigation";

export default function AppHeader() {
  const {
    repos, selectedRepo, setSelectedRepo, scopeRepoIds, setScopeRepos,
    setIngestionJob, setRepos, appMode,
    clientConfig, setClientConfig
  } = useGraphStore();

  const [githubUrl, setGithubUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [showPicker, setShowPicker] = useState(false);
  const [showIngest, setShowIngest] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const ingestButtonRef = useRef<HTMLButtonElement>(null);
  const scopeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isPreviewMode()) return;
    api.listRepos().then((data) => {
      if (data && data.repos) {
        setRepos(data.repos);
        const currentRepo = useGraphStore.getState().selectedRepo;
        if (!currentRepo && data.repos.length > 0) {
          setSelectedRepo(data.repos[0]);
          setScopeRepos([data.repos[0].id]);
        }
      }
    }).catch(() => {});
  }, [setRepos, setScopeRepos, setSelectedRepo]);

  useEffect(() => {
    if (clientConfig) return;
    api.getClientConfig().then(setClientConfig).catch(() => {});
  }, [clientConfig, setClientConfig]);

  const closeIngest = () => {
    setShowIngest(false);
    window.requestAnimationFrame(() => ingestButtonRef.current?.focus());
  };
  const closeScopePicker = () => {
    setShowPicker(false);
    window.requestAnimationFrame(() => scopeButtonRef.current?.focus());
  };
  useEffect(() => {
    if (!showIngest) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeIngest();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showIngest]);

  const activeRepoIds = effectiveRepoIds(repos, scopeRepoIds, selectedRepo);
  const managedRepo = activeRepoIds.length === 1
    ? repos.find((repo) => repo.id === activeRepoIds[0]) ?? selectedRepo
    : null;
  const scopedRepo = scopeRepoIds.length === 1
    ? repos.find((repo) => repo.id === scopeRepoIds[0])
    : null;
  const repoButtonLabel = repos.length === 0
    ? "Select repositories…"
    : scopeRepoIds.length === 0
      ? `All ${repos.length} repos`
      : scopedRepo
        ? `${scopedRepo.owner}/${scopedRepo.repo}`
        : `${scopeRepoIds.length} repos`;

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
      closeIngest();
    }
  };

  const handleRefresh = async () => {
    if (!managedRepo) return;
    try {
      const result = await api.refreshRepo(managedRepo.id);
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
    if (!managedRepo) return;
    if (!confirm(`Delete ${managedRepo.name}? This cannot be undone.`)) return;
    try {
      await api.deleteRepo(managedRepo.id);
      const updated = await api.listRepos();
      setRepos(updated.repos);
      const next = updated.repos[0] ?? null;
      setSelectedRepo(next);
      setScopeRepos(next ? [next.id] : []);
    } catch (err: any) {
      useGraphStore.getState().setError(err.message);
    }
  };

  return (
    <header className="h-13 flex items-center px-4 gap-3 z-40 flex-shrink-0 bg-[#f4f1e9]/95 border-b border-[#c9c3b7] shadow-xs">
      {/* Brand Badge */}
      <div className="flex items-center gap-2.5 flex-shrink-0">
        <div className="w-7 h-7 rounded-md bg-[#20241f] flex items-center justify-center shadow-xs">
          <Box className="w-4 h-4 text-[#f4f1e9]" />
        </div>
        <div className="flex flex-col">
          <span className="text-xs font-bold tracking-tight text-slate-900 leading-none">EVIGRAPH</span>
          <span className="text-[9.5px] font-medium text-slate-400 leading-none mt-0.5">Code Intelligence</span>
        </div>
      </div>

      <div className="w-px h-5 bg-slate-200 mx-1" />

      <WorkspaceNavigation />

      <div className="w-px h-5 bg-slate-200 mx-1" />

      {/* Repo Dropdown */}
      <button
        ref={scopeButtonRef}
        onClick={() => setShowPicker(true)}
        aria-expanded={showPicker}
        aria-haspopup="dialog"
        className="flex items-center gap-2 px-3 py-1 rounded-lg text-xs font-medium min-w-[190px]
                   hover:bg-slate-50 transition-colors border border-slate-200 bg-white shadow-xs text-slate-800"
      >
        {appMode === "repo" ? (
          <GitBranch className="w-3.5 h-3.5 text-[#315b47] flex-shrink-0" />
        ) : (
          <Layers className="w-3.5 h-3.5 text-[#a45138] flex-shrink-0" />
        )}
        <span className="flex-1 text-left truncate font-medium">{repoButtonLabel}</span>
        <ChevronDown className="w-3.5 h-3.5 text-slate-400" />
      </button>
      {showPicker && <RepoPickerModal mode={appMode === "repo" ? "repo" : "multi"} onClose={closeScopePicker} />}

      {/* Search Omnibar */}
      {appMode === "repo" && (
        <div className="flex-1 min-w-[10rem] max-w-sm hidden lg:block">
          <GraphSearch />
        </div>
      )}

      {/* Ingest Button */}
      <div className="relative flex-shrink-0 ml-auto">
        <button
          ref={ingestButtonRef}
          onClick={() => showIngest ? closeIngest() : setShowIngest(true)}
          aria-expanded={showIngest}
          aria-haspopup="dialog"
          className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold
                     transition-colors bg-[#315b47] hover:bg-[#274a3a] text-white shadow-xs"
        >
          {ingesting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          <span>Ingest</span>
        </button>
        {showIngest && (
          <>
            <div className="fixed inset-0 z-40" onClick={closeIngest} />
            <form
              role="dialog"
              aria-label="Ingest a repository"
              onSubmit={(event) => { event.preventDefault(); handleIngest(); }}
              className="absolute top-full right-0 mt-1 z-50 w-80 rounded-xl p-3.5 space-y-2.5
                            bg-white border border-slate-200 shadow-lg">
              <label className="block text-2xs font-semibold text-slate-500 uppercase tracking-wider">
                Ingest a repository
              </label>
              <input
                type="url"
                autoFocus
                placeholder="https://github.com/owner/repo"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                className="w-full text-xs px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200
                           text-slate-900 outline-none focus:border-[#315b47] focus:bg-white"
              />
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  placeholder="branch (optional)"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="flex-1 text-xs px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-200
                             text-slate-900 outline-none focus:border-[#315b47] focus:bg-white"
                />
                <button
                  type="submit"
                  disabled={!githubUrl.trim() || ingesting}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors
                             bg-[#315b47] hover:bg-[#274a3a] text-white
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Ingest
                </button>
              </div>
            </form>
          </>
        )}
      </div>

      {appMode === "repo" && managedRepo && (
        <div className="flex items-center gap-1">
          <button
            onClick={handleRefresh}
            title="Refresh repository"
            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleDelete}
            title="Delete repository"
            className="p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-600 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </header>
  );
}
