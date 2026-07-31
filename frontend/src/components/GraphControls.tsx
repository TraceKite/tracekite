import {
  RotateCcw, Maximize, Minimize, Type,
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

  // Native fullscreen can legitimately be refused — an iframe without
  // allow="fullscreen", a lost user gesture, browser policy. The old version
  // swallowed that rejection and flipped the flag anyway, so the app entered
  // fullscreen LAYOUT while the browser did not: header hidden, sidebar
  // hidden (taking this very button with it), and no fullscreenchange event
  // for Escape to trigger. The only way out was a reload. Entering in-app
  // maximize on failure is fine now that App owns Escape and a floating exit.
  // Fire-and-forget, deliberately. requestFullscreen() returns a promise that
  // some embedders never settle at all — measured here: the handler ran, the
  // request was issued, and neither resolve nor reject ever arrived. Awaiting
  // it therefore hung forever and the button did nothing at all.
  //
  // Updating app state optimistically is safe now for a reason it was not
  // before: App owns the fullscreenchange sync, an Escape handler, and a
  // floating exit control, so entering this state can always be undone even
  // when the native request is refused or never answers.
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
      <h4 className="text-xs font-semibold text-[#8c949e] uppercase tracking-wider mb-2">
        Controls
      </h4>

      <div className="grid grid-cols-2 gap-1.5">
        <button
          onClick={graphControlCallbacks?.resetCamera}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 transition-colors"
          title="Reset camera"
        >
          <RotateCcw className="w-3 h-3" />
          <span>Reset</span>
        </button>

        <button
          onClick={graphControlCallbacks?.fitGraph}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 transition-colors"
          title="Fit graph to view"
        >
          <Maximize className="w-3 h-3" />
          <span>Fit</span>
        </button>

        <button
          onClick={graphControlCallbacks?.togglePhysics}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 transition-colors"
          title={physicsOn ? "Pause physics" : "Resume physics"}
        >
          {physicsOn ? <><Pause className="w-3 h-3" /><span>Pause</span></>
            : <><Play className="w-3 h-3" /><span>Resume</span></>}
        </button>

        <button
          onClick={() => setShowLabels(!showLabels)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
            showLabels ? "text-blue-400 bg-blue-500/10" : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5"
          }`}
          title="Toggle labels"
        >
          <Type className="w-3 h-3" />
          <span>Labels</span>
        </button>

        <button
          onClick={() => setShowParticles(!showParticles)}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
            showParticles ? "text-blue-400 bg-blue-500/10" : "text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5"
          }`}
          title="Toggle particles"
        >
          <Sparkles className="w-3 h-3" />
          <span>Particles</span>
        </button>

        <button
          onClick={toggleFullscreen}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 transition-colors"
          title="Toggle fullscreen"
        >
          {isFullscreen ? <Minimize className="w-3 h-3" /> : <Maximize className="w-3 h-3" />}
          <span>{isFullscreen ? "Exit" : "Full"}</span>
        </button>
      </div>
    </div>
  );
}
