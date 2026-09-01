import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { ServiceMapNode } from "@/lib/types";

export default function ServiceMapNavigator({
  nodes,
  focusedId,
  onSelect,
}: {
  nodes: ServiceMapNode[];
  focusedId?: string;
  onSelect: (node: ServiceMapNode | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    return nodes
      .filter((node) => node.kind === "service" &&
        (node.name.toLowerCase().includes(needle) || node.id.toLowerCase().includes(needle)))
      .sort((left, right) => left.name.localeCompare(right.name))
      .slice(0, 12);
  }, [nodes, query]);

  const clear = () => {
    setQuery("");
    setOpen(false);
    onSelect(null);
  };

  return (
    <div className="absolute right-4 top-4 z-30 w-64"
         onPointerDown={(event) => event.stopPropagation()}>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#8a8e84]" />
        <input
          type="search"
          aria-label="Find a service on the map"
          placeholder="Find a service…"
          value={query}
          onFocus={() => setOpen(true)}
          onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
          onKeyDown={(event) => {
            if (event.key === "Escape") { setOpen(false); event.currentTarget.blur(); }
          }}
          className="w-full rounded-md border border-[#c9c3b7] bg-[#fffefa]/95 py-2 pl-8 pr-8
                     text-xs text-[#252821] shadow-sm outline-none placeholder:text-[#8a8e84]"
        />
        {(query || focusedId) && (
          <button onClick={clear} aria-label="Clear service search and focus"
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[#8a8e84] hover:text-[#252821]">
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {open && query && (
        <div className="mt-1 max-h-72 overflow-y-auto rounded-md border border-[#c9c3b7]
                        bg-[#fffefa] py-1 shadow-lg">
          {matches.map((node) => (
            <button key={node.id} aria-label={`${node.name}, service ${node.id}`} onClick={() => {
              setQuery(node.name); setOpen(false); onSelect(node);
            }} className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left
                           text-xs text-[#252821] hover:bg-[#f4f1e9]">
              <span className="truncate">{node.name}</span>
              <span className="shrink-0 text-2xs text-[#8a8e84]">service</span>
            </button>
          ))}
          {matches.length === 0 && (
            <p className="px-3 py-3 text-center text-2xs text-[#6e7168]">No service matches.</p>
          )}
        </div>
      )}
    </div>
  );
}
