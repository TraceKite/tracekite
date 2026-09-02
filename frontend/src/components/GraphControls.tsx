import {
  RotateCcw, RotateCw, Maximize, Minimize, Type,
  Sparkles, Pause, Play,
} from "lucide-react";
import { useGraphStore } from "@/store/graphStore";

export default function GraphControls() {
  const {
    showLabels, setShowLabels,
    showParticles, setShowParticles,
    isFullscreen, setIsFullscreen,
    graphControlCallbacks,
  } = useGraphStore();

  const toggleFullscreen = () => {
    if (!isFullscreen) {
      document.documentElement.requestFullscreen?.().catch(() => {});
      setIsFullscreen(true);
    } else {
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const physicsOn = graphControlCallbacks?.physicsEnabled ?? true;

  return (
    <div className="space-y-2">
      <h4 className="text-2xs font-semibold text-slate-400 uppercase tracking-wider">
        Controls
      </h4>

      <div className="grid grid-cols-2 gap-1.5">
        <button
          onClick={graphControlCallbacks?.resetCamera}
          disabled={!graphControlCallbacks?.resetCamera}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors disabled:cursor-wait disabled:opacity-40"
          title="Reset camera"
        >
          <RotateCcw className="w-3 h-3 text-slate-400" />
          <span>Reset</span>
        </button>

        <button
          onClick={graphControlCallbacks?.fitGraph}
          disabled={!graphControlCallbacks?.fitGraph}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors disabled:cursor-wait disabled:opacity-40"
          title="Fit graph to view"
        >
          <Maximize className="w-3 h-3 text-slate-400" />
          <span>Fit</span>
        </button>

        <button
          onClick={graphControlCallbacks?.rotateGraph}
          disabled={!graphControlCallbacks?.rotateGraph}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 transition-colors disabled:cursor-wait disabled:opacity-40"
          title="Rotate layout 90 degrees"
        >
          <RotateCw className="w-3 h-3 text-slate-400" />
          <span>Rotate</span>
        </button>

        <button
          onClick={graphControlCallbacks?.togglePhysics}
          disabled={!graphControlCallbacks?.togglePhysics}
          aria-pressed={!physicsOn}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            !physicsOn ? "bg-slate-900 text-white shadow-xs font-semibold" : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
          }`}
          title={physicsOn ? "Settle layout forces; navigation remains active" : "Re-run layout forces"}
        >
          {physicsOn ? <><Pause className="w-3 h-3" /><span>Settle</span></>
            : <><Play className="w-3 h-3" /><span>Re-layout</span></>}
        </button>

        <button
          onClick={() => setShowLabels(!showLabels)}
          aria-pressed={showLabels}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            showLabels ? "bg-slate-900 text-white shadow-xs font-semibold" : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
          }`}
          title="Toggle billboard labels"
        >
          <Type className="w-3 h-3" />
          <span>Labels</span>
        </button>

        <button
          onClick={() => setShowParticles(!showParticles)}
          aria-pressed={showParticles}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
            showParticles ? "bg-slate-900 text-white shadow-xs font-semibold" : "text-slate-600 hover:text-slate-900 hover:bg-slate-100"
          }`}
          title="Toggle directional flow particles"
        >
          <Sparkles className="w-3 h-3" />
          <span>Particles</span>
        </button>
      </div>

      <button
        onClick={toggleFullscreen}
        aria-pressed={isFullscreen}
        title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
        className="w-full flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-slate-200 transition-colors"
      >
        {isFullscreen ? <Minimize className="w-3 h-3" /> : <Maximize className="w-3 h-3" />}
        <span>{isFullscreen ? "Exit Fullscreen" : "Fullscreen"}</span>
      </button>
    </div>
  );
}
