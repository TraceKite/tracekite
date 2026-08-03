/** Service Picker Modal — multi-repository service selector for Trace view.
 *
 * Distributed trace paths span multi-repo graphs. This modal lists all available
 * microservices, databases, queues, and external systems tagged by their parent
 * repository, allowing engineers to pick Origin and Destination endpoints across
 * any repository in the active estate.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Search, X, Server, Database, Radio, Globe } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";

interface Props {
  title: string;
  selectedService: string;
  onSelect: (serviceName: string) => void;
  onClose: () => void;
}

export default function ServicePickerModal({ title, selectedService, onSelect, onClose }: Props) {
  const { serviceMapData, scopeRepoIds, repos } = useGraphStore();
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Extract all services, DB tables, and topics with repository metadata
  const servicesList = useMemo(() => {
    const nodes = serviceMapData?.nodes ?? [];
    const repoMap = new Map(repos.map((r) => [r.id, r.repo]));

    return nodes.map((n: any) => {
      const repoNames = (n.repo_ids ?? [])
        .map((id: string) => repoMap.get(id) || id)
        .filter(Boolean);
      const isDB = n.kind === "database" || n.name.includes("db") || n.name.includes("mongodb");
      const isTopic = n.kind === "topic" || n.name.includes("kafka") || n.name.includes("rabbitmq");
      const isExternal = n.kind === "external";

      return {
        id: n.id || n.name,
        name: n.name as string,
        kind: n.kind || (isDB ? "database" : isTopic ? "topic" : "service"),
        repoNames,
        repoIds: n.repo_ids ?? [],
        inScope: scopeRepoIds.length === 0 || (n.repo_ids ?? []).some((id: string) => scopeRepoIds.includes(id)),
      };
    }).sort((a, b) => a.name.localeCompare(b.name));
  }, [serviceMapData, scopeRepoIds, repos]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return servicesList;
    return servicesList.filter((s) =>
      s.name.toLowerCase().includes(q) ||
      s.repoNames.some((r: string) => r.toLowerCase().includes(q)) ||
      s.kind.toLowerCase().includes(q)
    );
  }, [servicesList, query]);

  const getKindIcon = (kind: string) => {
    if (kind === "database") return <Database className="w-3.5 h-3.5 text-purple-400 shrink-0" />;
    if (kind === "topic") return <Radio className="w-3.5 h-3.5 text-teal-400 shrink-0" />;
    if (kind === "external") return <Globe className="w-3.5 h-3.5 text-amber-400 shrink-0" />;
    return <Server className="w-3.5 h-3.5 text-violet-400 shrink-0" />;
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed left-1/2 top-20 z-50 w-[min(92vw,34rem)] -translate-x-1/2 rounded-xl
                   bg-[#15181c] border border-[#2b313a] shadow-2xl overflow-hidden"
        style={{ animation: "fadeIn 0.15s ease-out" }}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#2b313a]">
          <div>
            <h2 className="text-sm font-bold text-[#e9ecef]">{title}</h2>
            <p className="text-2xs text-[#8c949e] mt-0.5">
              Select a service endpoint across multi-repository estates.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="text-[#8c949e] hover:text-white p-1"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-4 py-2 border-b border-[#2b313a]">
          <div className="flex items-center gap-2 bg-black/30 rounded-lg px-2.5 py-1.5
                          border border-white/5 focus-within:border-violet-500/50">
            <Search className="w-3.5 h-3.5 text-[#8c949e] shrink-0" />
            <input
              ref={searchRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter services by name, repo, or kind…"
              className="flex-1 bg-transparent text-sm text-[#e9ecef] outline-none
                         placeholder:text-[#5c636d]"
            />
          </div>
        </div>

        <div className="max-h-[50vh] overflow-y-auto py-1">
          {filtered.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-[#8c949e]">
              No service matches “{query}”.
            </p>
          )}
          {filtered.map((item) => {
            const isSelected = selectedService === item.name;
            return (
              <button
                key={item.id}
                onClick={() => {
                  onSelect(item.name);
                  onClose();
                }}
                className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors
                            hover:bg-white/5 ${isSelected ? "bg-violet-500/10 border-l-2 border-violet-400" : ""}`}
              >
                {getKindIcon(item.kind)}
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium text-[#e9ecef] truncate">{item.name}</span>
                  {item.repoNames.length > 0 && (
                    <span className="block text-2xs text-[#8c949e] truncate">
                      {item.repoNames.join(", ")}
                    </span>
                  )}
                </span>
                <span className="text-3xs uppercase font-semibold px-2 py-0.5 rounded bg-white/5 text-[#8c949e]">
                  {item.kind}
                </span>
              </button>
            );
          })}
        </div>

        <div className="px-4 py-2.5 border-t border-[#2b313a] flex items-center justify-between text-2xs text-[#8c949e]">
          <span>{filtered.length} endpoints available</span>
          <button onClick={onClose} className="hover:text-white">Cancel</button>
        </div>
      </div>
    </>
  );
}
