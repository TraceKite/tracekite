import { ArrowLeft, Box, Crosshair, Layers3 } from "lucide-react";

import type { ProjectionMode } from "@/hooks/useGraphProjection";
import type { ViewMode } from "@/lib/types";

interface Props {
  projectionMode: ProjectionMode;
  viewMode: ViewMode;
  expandedGroup: string | null;
  /** The node the canvas has been opened into, not the one being read. */
  openedLabel: string | null;
  hasSelection: boolean;
  visibleNodeCount: number;
  visibleEdgeCount: number;
  loadedNodeCount: number;
  eligibleNodeCount: number;
  totalNodeCount: number;
  activePath?: boolean;
  onBack: () => void;
}

function modeLabel(mode: ViewMode): string {
  if (mode === "impact") return "Impact · 2 hops";
  return mode[0].toUpperCase() + mode.slice(1);
}

export default function GraphContextBar({
  projectionMode, viewMode, expandedGroup, openedLabel, hasSelection,
  visibleNodeCount, visibleEdgeCount, loadedNodeCount, activePath = false,
  eligibleNodeCount, totalNodeCount,
  onBack,
}: Props) {
  const canGoBack = activePath || hasSelection || Boolean(openedLabel) ||
    Boolean(expandedGroup);
  const title = activePath
    ? "Directed path"
    : projectionMode === "focus"
      ? viewMode === "impact"
        ? `Impact · ${openedLabel ?? "selection"}`
        : openedLabel ?? "Focus"
      : projectionMode === "group"
        ? expandedGroup ?? "Module"
        : modeLabel(viewMode);
  const detail = viewMode === "impact" && projectionMode === "focus"
    ? `2 hops · ${visibleNodeCount}${totalNodeCount > visibleNodeCount ? ` of ${totalNodeCount}` : ""} nodes · ${visibleEdgeCount} exact edges`
    : projectionMode === "overview"
    ? `${visibleNodeCount} groups · ${eligibleNodeCount < loadedNodeCount
      ? `${eligibleNodeCount} eligible of ${loadedNodeCount}`
      : loadedNodeCount} loaded`
    : totalNodeCount > visibleNodeCount
      ? `${visibleNodeCount} of ${totalNodeCount} nodes · ${visibleEdgeCount} exact edges`
      : `${visibleNodeCount} nodes · ${visibleEdgeCount} edges`;
  const Icon = projectionMode === "focus" ? Crosshair
    : projectionMode === "group" ? Box : Layers3;

  return (
    <div
      className="absolute top-4 left-4 z-30 flex max-w-[min(70%,46rem)] items-center gap-2
                 rounded-md border border-[#c9c3b7] bg-[#fffefa]/95 px-2.5 py-1.5
                 text-2xs text-[#6e7168] shadow-sm backdrop-blur-sm"
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
    >
      {canGoBack && (
        <button
          onClick={onBack}
          className="-ml-1 inline-flex items-center gap-1 rounded px-1.5 py-1 font-semibold
                     text-[#315b47] hover:bg-[#315b47]/10"
          title="Back one level (Escape)"
        >
          <ArrowLeft className="h-3 w-3" /> Back
        </button>
      )}
      <Icon className="h-3.5 w-3.5 shrink-0 text-[#6b6f65]" />
      <span className="truncate font-semibold text-[#252821]" title={title}>{title}</span>
      <span className="shrink-0 border-l border-[#d4cfc3] pl-2 font-mono">{detail}</span>
    </div>
  );
}
