import {
  Type,
  Minus,
  Plus,
  Compass,
  Zap,
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";

interface Props {
  onZoom: (factor: number) => void;
  onResetZoom: () => void;
  onResetView: () => void;
  zoomLevel: number;
}

export default function Graph3DTools({ onZoom, onResetZoom, onResetView, zoomLevel }: Props) {
  const {
    showLabels,
    setShowLabels,
    hideLockfileDeps,
    toggleHideLockfileDeps,
  } = useGraphStore();

  return (
    <div
      role="toolbar"
      aria-label="3D graph controls"
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 bg-[#f4f1e9]/95 px-3 py-1.5 rounded-lg border border-[#c9c3b7] shadow-lg"
    >
      <div className="flex items-center gap-1">
        <button
          onClick={toggleHideLockfileDeps}
          aria-pressed={hideLockfileDeps}
          className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium transition-all ${
            hideLockfileDeps
              ? "bg-[#315b47] text-white shadow-xs font-semibold"
              : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
          }`}
          title="Hide dependency leaves emitted from lockfiles"
        >
          <Zap className="w-3.5 h-3.5" />
          <span>Less noise</span>
        </button>

        <button
          onClick={() => setShowLabels(!showLabels)}
          aria-pressed={showLabels}
          className={`flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-medium transition-all ${
            showLabels
              ? "bg-[#315b47] text-white shadow-xs font-semibold"
              : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
          }`}
          title="Toggle 3D billboard labels"
        >
          <Type className="w-3.5 h-3.5" />
          <span>Labels</span>
        </button>

      </div>

      <div className="w-px h-4 bg-slate-200 mx-1" />

      {/* Camera Dolly & Zoom */}
      <div className="flex items-center gap-1">
        <button
          onClick={() => onZoom(0.8)}
          aria-label="Zoom in"
          className="p-1.5 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          title="Zoom In"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={onResetZoom}
          aria-label="Reset zoom to 100 percent"
          className="text-2xs font-mono text-slate-500 hover:text-slate-900 select-none px-1 rounded hover:bg-slate-100"
          title="Reset Zoom Level"
        >
          {Math.round(zoomLevel * 100)}%
        </button>
        <button
          onClick={() => onZoom(1.2)}
          aria-label="Zoom out"
          className="p-1.5 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          title="Zoom Out"
        >
          <Minus className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="w-px h-4 bg-slate-200 mx-1" />

      {/* Action Controls */}
      <div className="flex items-center gap-1">
        <button
          onClick={onResetView}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors"
          title="Reset camera orientation and zoom"
        >
          <Compass className="w-3.5 h-3.5" />
          <span>Reset</span>
        </button>
      </div>
    </div>
  );
}
