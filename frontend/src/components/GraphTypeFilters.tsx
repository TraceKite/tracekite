import { useState, useCallback, useMemo } from "react";
import { Filter, ChevronDown, ChevronRight, Eye, EyeOff } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { EDGE_COLORS } from "@/lib/graphStyle";
import { tallyTypes } from "@/lib/typeTally";

function SectionToggle({ label, hiddenCount, open, onToggle }: {
  label: string; hiddenCount: number; open: boolean; onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      aria-expanded={open}
      className="flex items-center gap-1.5 text-2xs font-semibold text-slate-400 uppercase tracking-wider mb-2 hover:text-slate-700 transition-colors w-full"
    >
      <Filter className="w-3 h-3" />
      <span>{label}{hiddenCount > 0 && ` · ${hiddenCount} hidden`}</span>
      {open ? <ChevronDown className="w-3 h-3 ml-auto" /> : <ChevronRight className="w-3 h-3 ml-auto" />}
    </button>
  );
}

const countClass = "ml-auto text-2xs text-slate-400 font-mono";
const countTitle = "Returned in this view";

export function NodeTypeFilter() {
  const { nodes, filteredNodeTypes, setFilteredNodeTypes } = useGraphStore();
  const [open, setOpen] = useState(false);
  const rows = useMemo(() => tallyTypes(nodes, filteredNodeTypes),
                       [nodes, filteredNodeTypes]);

  const toggle = useCallback((type: string) => {
    setFilteredNodeTypes((prev: string[]) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]);
  }, [setFilteredNodeTypes]);

  return (
    <div>
      <SectionToggle label="Node Types" hiddenCount={filteredNodeTypes.length}
                     open={open} onToggle={() => setOpen(!open)} />
      {open && (
        <div className="space-y-1">
          {rows.map(({ type, count }) => (
            <label key={type} className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-slate-100 cursor-pointer text-xs transition-colors">
              <input
                type="checkbox"
                checked={!filteredNodeTypes.includes(type)}
                onChange={() => toggle(type)}
                className="rounded border-slate-300 text-[#315b47] focus:ring-[#315b47]"
                style={{ accentColor: "#315b47" }}
              />
              <span className="text-slate-800">{type}</span>
              <span className={countClass} title={countTitle}>{count}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

export function EdgeTypeFilter() {
  const {
    links, filteredEdgeTypes, setFilteredEdgeTypes,
    highlightedEdgeTypes, toggleHighlightEdgeType, clearHighlightedEdgeTypes,
  } = useGraphStore();
  const [open, setOpen] = useState(false);
  const rows = useMemo(() => tallyTypes(links, filteredEdgeTypes),
                       [links, filteredEdgeTypes]);

  const toggle = useCallback((type: string) => {
    setFilteredEdgeTypes((prev: string[]) => {
      const hiding = !prev.includes(type);
      if (hiding && highlightedEdgeTypes.includes(type)) toggleHighlightEdgeType(type);
      return hiding ? [...prev, type] : prev.filter((t) => t !== type);
    });
  }, [setFilteredEdgeTypes, highlightedEdgeTypes, toggleHighlightEdgeType]);

  return (
    <div>
      <SectionToggle label="Edge Types" hiddenCount={filteredEdgeTypes.length}
                     open={open} onToggle={() => setOpen(!open)} />
      {open && (
        <div className="space-y-1">
          {highlightedEdgeTypes.length > 0 && (
            <button
              onClick={clearHighlightedEdgeTypes}
              className="w-full text-2xs px-2 py-1 rounded-md bg-slate-100
                         text-slate-600 hover:text-slate-900 transition-colors font-medium"
            >
              Clear highlight ({highlightedEdgeTypes.length})
            </button>
          )}
          {rows.map(({ type, count }) => {
            const hidden = filteredEdgeTypes.includes(type);
            const lit = highlightedEdgeTypes.includes(type);
            return (
              <div key={type} className="flex items-center gap-1">
                <button
                  onClick={() => toggleHighlightEdgeType(type)}
                  disabled={hidden}
                  aria-pressed={lit}
                  title={hidden ? "Hidden — show it to highlight"
                                : lit ? "Stop highlighting" : "Highlight these edges"}
                  className={`flex-1 flex items-center gap-2 px-2 py-1 rounded-md text-xs
                              text-left transition-colors disabled:cursor-not-allowed ${
                    lit ? "bg-slate-200 text-slate-900 font-semibold" : "hover:bg-slate-100 text-slate-700"}`}
                  style={{ opacity: hidden ? 0.35 : 1 }}
                >
                  <span className="w-3.5 h-0.5 rounded-full flex-shrink-0"
                        style={{ background: EDGE_COLORS[type] ?? "#94a3b8" }} />
                  <span className="truncate">{type}</span>
                  <span className={countClass} title={countTitle}>{count}</span>
                </button>
                <button
                  onClick={() => toggle(type)}
                  aria-label={hidden ? `Show ${type}` : `Hide ${type}`}
                  title={hidden ? "Show" : "Hide"}
                  className="p-1 rounded text-slate-400 hover:text-slate-700
                             hover:bg-slate-100 transition-colors flex-shrink-0"
                >
                  {hidden ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
