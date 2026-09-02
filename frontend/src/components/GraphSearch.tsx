import { useState, useRef, useCallback, useEffect } from "react";
import { Search, X, Loader2 } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import type { SearchResult } from "@/lib/types";
import { getNodeColor } from "@/lib/graphStyle";
import { effectiveRepoIds } from "@/lib/graphNavigation";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";

export default function GraphSearch() {
  const {
    repos, selectedRepo, scopeRepoIds, setSelectedNode, setFocusNode,
    searchQuery: query, setSearchQuery: setQuery, setViewMode, setError,
  } = useGraphStore();
  const clearExpandedGroup = useGraphNavigationStore(
    (state) => state.clearExpandedGroup);
  const repoIds = effectiveRepoIds(repos, scopeRepoIds, selectedRepo);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [showResults, setShowResults] = useState(false);
  const [searching, setSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<number | undefined>(undefined);
  const requestRef = useRef(0);

  const performSearch = useCallback(
    async (q: string) => {
      const requestId = ++requestRef.current;
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
        if (requestId === requestRef.current) {
          const all = per.flat();
          setResultTotal(all.length);
          setResults(all.slice(0, 50));
          setShowResults(true);
        }
      } catch (err: any) {
        if (requestId === requestRef.current) setError(err.message);
      } finally {
        if (requestId === requestRef.current) setSearching(false);
      }
    },
    [repoIds.join(","), setError],
  );

  useEffect(() => () => {
    requestRef.current += 1;
    if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
  }, []);

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
      requestRef.current += 1;
      setResults([]);
      setResultTotal(0);
      setShowResults(false);
    }
  };

  const handleSelectResult = (result: SearchResult) => {
    const repoId = (result as any).repo_id;
    clearExpandedGroup();
    setViewMode("overview");
    setFocusNode(result.id, repoId);
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
      repo_id: repoId,
      metadata: {},
    } as any);
    setQuery(result.label);
    setShowResults(false);
  };

  const clearSearch = () => {
    requestRef.current += 1;
    setQuery("");
    setResults([]);
    setResultTotal(0);
    setShowResults(false);
    inputRef.current?.focus();
  };

  return (
    <div className="relative">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#8b929e]" />
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
            background: "#fbf9f3",
            border: "1px solid #c9c3b7",
            borderRadius: "8px",
            color: "#1a1d23",
            outline: "none",
          }}
        />
        {query && (
          <button onClick={clearSearch} aria-label="Clear search" className="absolute right-3 top-1/2 -translate-y-1/2 text-[#8b929e] hover:text-[#1a1d23]">
            <X className="w-3.5 h-3.5" />
          </button>
        )}
        {searching && (
          <Loader2 className="absolute right-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#9b7a31] animate-spin" />
        )}
      </div>

      {showResults && results.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 rounded-lg shadow-sm z-50 max-h-64 overflow-y-auto"
          style={{ background: "#f4f1e9", border: "1px solid #c9c3b7", animation: "fadeIn 0.2s ease-out" }}
        >
          {results.map((result) => (
            <button
              key={`${(result as any).repo_id}:${result.id}`}
              onClick={() => handleSelectResult(result)}
              className="w-full text-left px-3 py-2 hover:bg-slate-100 transition-colors flex items-center gap-2"
            >
              <span className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ background: getNodeColor(result.type) }} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-[#1a1d23] truncate">{result.label}</p>
                <p className="text-2xs text-[#8b929e] truncate">
                  {repos.find((repo) => repo.id === (result as any).repo_id)?.repo}
                  {result.path && ` · ${result.path}`}
                </p>
              </div>
              <span className="text-2xs text-[#8b929e] bg-[#dfe2e8] px-1.5 py-0.5 rounded flex-shrink-0">{result.type}</span>
            </button>
          ))}
          {resultTotal > results.length && (
            <p className="border-t border-[#d4cfc3] px-3 py-2 text-center text-2xs text-[#6e7168]">
              Showing first {results.length} of {resultTotal} matches. Refine the query to narrow.
            </p>
          )}
        </div>
      )}

      {showResults && query.length >= 2 && results.length === 0 && !searching && (
        <div className="absolute top-full left-0 right-0 mt-1 rounded-lg z-50 p-3"
          style={{ background: "#f4f1e9", border: "1px solid #c9c3b7", animation: "fadeIn 0.2s ease-out" }}
        >
          <p className="text-xs text-[#8b929e] text-center">No results found</p>
        </div>
      )}

      {showResults && <div className="fixed inset-0 z-40" onClick={() => setShowResults(false)} />}
    </div>
  );
}
