import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Server, X } from "lucide-react";
import type { ServiceMapNode } from "@/lib/types";
import { useGraphStore } from "@/store/graphStore";

interface Props {
  title: string;
  selectedService: string;
  onSelect: (serviceId: string) => void;
  onClose: () => void;
}
interface ServiceChoice {
  id: string;
  name: string;
  repoNames: string[];
}

export default function ServicePickerModal({
  title, selectedService, onSelect, onClose,
}: Props) {
  const { serviceMapData, scopeRepoIds, repos } = useGraphStore();
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    searchRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const services = useMemo<ServiceChoice[]>(() => {
    const repoNames = new Map(repos.map((repo) => [repo.id, repo.repo]));
    return (serviceMapData?.nodes ?? [])
      .filter((node: ServiceMapNode) =>
        node.kind === "service" &&
        (scopeRepoIds.length === 0 ||
         (node.repo_ids ?? []).some((id) => scopeRepoIds.includes(id))))
      .map((node) => ({
        id: node.id,
        name: node.name,
        repoNames: (node.repo_ids ?? []).map((id) => repoNames.get(id) ?? id),
      }))
      .sort((left, right) =>
        left.name.localeCompare(right.name) || left.id.localeCompare(right.id));
  }, [serviceMapData, scopeRepoIds, repos]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return services;
    return services.filter((service) =>
      service.name.toLowerCase().includes(needle) ||
      service.id.toLowerCase().includes(needle) ||
      service.repoNames.some((repo) => repo.toLowerCase().includes(needle)));
  }, [services, query]);

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/30"
           onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="fixed left-1/2 top-20 z-50 w-[min(92vw,34rem)] -translate-x-1/2
                   rounded-xl bg-white border border-[#dfe2e8] shadow-sm
                   overflow-hidden"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-[#dfe2e8]">
          <div>
            <h2 className="text-sm font-bold text-[#1a1d23]">{title}</h2>
            <p className="text-2xs text-[#8b929e] mt-0.5">
              Select a repository-backed service.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close"
                  className="text-[#8b929e] hover:text-[#1a1d23] p-1">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-4 py-2 border-b border-[#dfe2e8]">
          <div className="flex items-center gap-2 bg-slate-50 rounded-lg px-2.5
                          py-1.5 border border-slate-200 focus-within:border-[#315b47]">
            <Search className="w-3.5 h-3.5 text-[#8b929e] shrink-0" />
            <input
              ref={searchRef}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter by service, node ID, or repository…"
              className="flex-1 bg-transparent text-sm text-[#1a1d23] outline-none
                         placeholder:text-[#9ca3af]"
            />
          </div>
        </div>

        <div className="max-h-[50vh] overflow-y-auto py-1">
          {filtered.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-[#8b929e]">
              No service matches “{query}”.
            </p>
          )}
          {filtered.map((service) => (
            <button
              key={service.id}
              onClick={() => {
                onSelect(service.id);
                onClose();
              }}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left
                          transition-colors hover:bg-slate-50 ${
                            selectedService === service.id
                              ? "bg-[#315b47]/10 border-l-2 border-[#315b47]"
                              : ""
                          }`}
            >
              <Server className="w-3.5 h-3.5 text-[#315b47] shrink-0" />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-medium text-[#1a1d23] truncate">
                  {service.name}
                </span>
                <span className="block text-2xs text-[#8b929e] truncate">
                  {service.repoNames.join(", ") || service.id}
                </span>
              </span>
              <span className="text-3xs uppercase font-semibold px-2 py-0.5
                               rounded bg-slate-100 text-[#8b929e]">
                service
              </span>
            </button>
          ))}
        </div>

        <div className="px-4 py-2.5 border-t border-[#dfe2e8] flex items-center
                        justify-between text-2xs text-[#8b929e]">
          <span>{filtered.length} services available</span>
          <button onClick={onClose} className="hover:text-[#1a1d23]">Cancel</button>
        </div>
      </div>
    </>
  );
}
