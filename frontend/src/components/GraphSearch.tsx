import { useState, useRef, useCallback } from "react";
import { Search, X, Loader2 } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import type { SearchResult } from "@/lib/types";

export default function GraphSearch() {
  const { selectedRepo, scopeRepoIds, setSelectedNode, setError } = useGraphStore();
  // The Repo view can now draw several repositories, so searching only
  // `selectedRepo` would quietly miss most of what is on screen.
  const repoIds = scopeRepoIds.length > 0
    ? scopeRepoIds
    : selectedRepo ? [selectedRepo.id] : [];
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [showResults, setShowResults] = useState(false);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<number | undefined>(undefined);

  const performSearch = useCallback(
    async (q: string) => {
      if (repoIds.length === 0 || q.length < 2) {
        setResults([]);
        return;
      }
      setSearching(true);
      try {
        // One repo failing must not blank the whole result list.
        const per = await Promise.all(repoIds.map((id) =>
          api.searchNodes(id, q)
            .then((d) => d.results.map((r: any) => ({ ...r, repo_id: id })))
            .catch(() => [])));
        setResults(per.flat());
        setShowResults(true);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setSearching(false);
      }
    },
    [repoIds.join(","), setError],
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
    }
    
    if (val.length >= 2) {
      timeoutRef.current = window.setTimeout(() => {
        performSearch(val);
      }, 300);
    } else {
      setResults([]);
      setShowResults(false);
    }
  };

  const handleSelectResult = (result: SearchResult) => {
    setSelectedNode({
      id: result.id,
      type: result.type,
      label: result.label,
      name: result.label,
      path: result.path || undefined,
      size: 8,
      group: result.type,
      // Which repo answered. Without it the drawer asks the wrong repo for
      // details, and "show it on the graph" has nothing to focus.
      repo_id: (result as any).repo_id,
      metadata: {},
    } as any);
    setQuery(result.label);
    setShowResults(false);
  };

  const clearSearch = () => {
    setQuery("");
    setResults([]);
    setShowResults(false);
    inputRef.current?.focus();
  };

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#8c949e]" />
        <input
          ref={inputRef}
          type="text"
          placeholder="Search files, classes, endpoints…"
          value={query}
          onChange={handleInputChange}
          onFocus={() => results.length > 0 && setShowResults(true)}
          disabled={repoIds.length === 0}
          className="w-full pl-9 pr-8 py-2 text-sm"
          style={{
            background: "rgba(30,41,59,0.9)",
            border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: "8px",
            color: "#e9ecef",
            outline: "none",
          }}
        />
        {query && (
          <button onClick={clearSearch} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#8c949e] hover:text-[#e9ecef]">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {searching && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-blue-400 animate-spin" />
        )}
      </div>

      {showResults && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 rounded-lg shadow-2xl z-50 max-h-64 overflow-y-auto"
          style={{ background: "rgba(17,24,39,0.95)", border: "1px solid rgba(255,255,255,0.08)", backdropFilter: "blur(12px)", animation: "fadeIn 0.2s ease-out" }}
        >
          {results.map((result) => (
            <button
              key={result.id}
              onClick={() => handleSelectResult(result)}
              className="w-full text-left px-3 py-2 hover:bg-white/5 transition-colors flex items-center gap-2"
            >
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                result.type === "Class" ? "bg-purple-400" :
                result.type === "Method" || result.type === "Function" ? "bg-green-400" :
                result.type === "File" ? "bg-slate-400" :
                result.type === "ApiEndpoint" ? "bg-red-400" :
                result.type === "Dependency" ? "bg-yellow-400" :
                result.type === "Folder" ? "bg-blue-400" :
                "bg-blue-400"
              }`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-[#e9ecef] truncate">{result.label}</p>
                {result.path && <p className="text-2xs text-[#8c949e] truncate">{result.path}</p>}
              </div>
              <span className="text-2xs text-[#8c949e] bg-[#2b313a] px-1.5 py-0.5 rounded flex-shrink-0">{result.type}</span>
            </button>
          ))}
        </div>
      )}

      {showResults && query.length >= 2 && results.length === 0 && !searching && (
        <div className="absolute top-full left-0 right-0 mt-1 rounded-lg z-50 p-3"
          style={{ background: "rgba(17,24,39,0.95)", border: "1px solid rgba(255,255,255,0.08)", animation: "fadeIn 0.2s ease-out" }}
        >
          <p className="text-xs text-[#8c949e] text-center">No results found</p>
        </div>
      )}

      {showResults && <div className="fixed inset-0 z-40" onClick={() => setShowResults(false)} />}
    </div>
  );
}