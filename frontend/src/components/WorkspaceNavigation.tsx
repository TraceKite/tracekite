import { GitBranch, Network, Zap } from "lucide-react";

import { useGraphStore } from "@/store/graphStore";

const MODES = [
  { id: "repo", label: "Repo", icon: GitBranch, color: "text-[#315b47]" },
  { id: "service_map", label: "Service Map", icon: Network, color: "text-[#a45138]" },
  { id: "trace", label: "Trace", icon: Zap, color: "text-[#9b7a31]" },
] as const;

export default function WorkspaceNavigation() {
  const {
    appMode, setAppMode, dimension, setDimension, setSelectedEdge,
    setActivePath3d,
  } = useGraphStore();

  return (
    <>
      <nav aria-label="Workspace" className="flex shrink-0 items-center rounded-lg border border-[#d4cfc3] bg-[#ebe8df] p-0.5">
        {MODES.map(({ id, label, icon: Icon, color }) => (
          <button
            key={id}
            onClick={() => setAppMode(id)}
            aria-current={appMode === id ? "page" : undefined}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs transition-colors ${
              appMode === id
                ? "bg-[#fffefa] font-semibold text-[#252821] shadow-sm"
                : "text-[#6e7168] hover:bg-[#fffefa]/60 hover:text-[#252821]"
            }`}
          >
            <Icon className={`h-3.5 w-3.5 ${color}`} /> {label}
          </button>
        ))}
      </nav>

      {appMode === "repo" && (
        <div aria-label="Graph projection" className="flex shrink-0 items-center rounded-lg border border-[#d4cfc3] bg-[#ebe8df] p-0.5">
          {(["2d", "3d"] as const).map((value) => (
            <button
              key={value}
              onClick={() => {
                if (dimension === value) return;
                setSelectedEdge(null);
                setActivePath3d(null);
                setDimension(value);
              }}
              aria-pressed={dimension === value}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold uppercase transition-colors ${
                dimension === value
                  ? "bg-[#315b47] text-white shadow-sm"
                  : "text-[#6e7168] hover:text-[#252821]"
              }`}
            >
              {value}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
