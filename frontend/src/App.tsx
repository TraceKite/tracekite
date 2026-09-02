import { useEffect } from "react";
import { Minimize } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { isModuleGroup } from "@/lib/graphOverviewProjection";
import { api } from "@/lib/api";
import {
  isPreviewMode, PREVIEW_REPOS, PREVIEW_SERVICE_MAP, PREVIEW_TRACE, PREVIEW_REPO_GRAPH,
} from "@/lib/previewFixtures";
import AppHeader from "@/components/AppHeader";
import RepoGraphView from "@/components/RepoGraphView";
import ServiceMapView from "@/components/ServiceMapView";
import TraceView from "@/components/TraceView";
import NodeDetailsDrawer from "@/components/NodeDetailsDrawer";
import ModuleDetailsDrawer from "@/components/ModuleDetailsDrawer";
import EdgeDetailsDrawer from "@/components/EdgeDetailsDrawer";
import AuthModal from "@/components/AuthModal";
import ErrorBoundary from "@/components/ErrorBoundary";
import IngestionStatus from "@/components/IngestionStatus";

function HomePage() {
  const { isFullscreen, appMode, selectedNode, selectedEdge, ingestionJob } = useGraphStore();

  // Fixture mode (?preview=1): render the real components against mock data so
  // the UI can be reviewed without a token. Client-side only — no API access.
  useEffect(() => {
    if (!isPreviewMode()) return;
    const store = useGraphStore.getState();
    store.setRepos(PREVIEW_REPOS);
    store.setSelectedRepo(PREVIEW_REPOS[0]);
    store.setServiceMapData(PREVIEW_SERVICE_MAP);
    store.setTraceData(PREVIEW_TRACE);
    store.setGraphData(PREVIEW_REPO_GRAPH.nodes, PREVIEW_REPO_GRAPH.links, PREVIEW_REPO_GRAPH.stats);
  }, []);

  // Fullscreen must be escapable from here, not from the sidebar: entering it
  // unmounts the sidebar, which is where the Exit button lives. This effect
  // also lived in GraphCanvas2D, which is only mounted in repo mode with a
  // repo selected — so the browser's own exit could go unnoticed.
  useEffect(() => {
    const onFullscreenChange = () => {
      if (!document.fullscreenElement) useGraphStore.getState().setIsFullscreen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      // When native fullscreen is active the browser handles Escape and we
      // sync via fullscreenchange. This covers the in-app maximize fallback,
      // where no such event is ever fired.
      if (e.key === "Escape" && useGraphStore.getState().isFullscreen) {
        useGraphStore.getState().setIsFullscreen(false);
      }
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const exitFullscreen = async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen?.();
    } catch {
      /* leave app fullscreen regardless */
    }
    useGraphStore.getState().setIsFullscreen(false);
  };

  return (
    <ErrorBoundary>
      <div className={`flex flex-col ${isFullscreen ? "fixed inset-0 z-50 bg-[#f8f9fb]" : "h-[100dvh] bg-[#f8f9fb]"}`}>
        {!isFullscreen && <AppHeader />}
        {isFullscreen && (
          <button
            onClick={exitFullscreen}
            className="fixed top-4 right-4 z-[60] inline-flex items-center gap-2 px-3 py-2 rounded-md
                       text-sm font-medium bg-slate-800/80 hover:bg-slate-800/90 border border-slate-600
                       text-white backdrop-blur-sm transition-colors"
          >
            <Minimize className="w-4 h-4" />
            Exit fullscreen
            <kbd className="ml-1 text-2xs text-slate-300 border border-slate-500 rounded px-1">Esc</kbd>
          </button>
        )}

        <div className="flex flex-1 overflow-hidden relative">
          {appMode === "repo" && <RepoGraphView />}
          {appMode === "service_map" && <ServiceMapView />}
          {appMode === "trace" && <TraceView />}

          {/* Rendered for EVERY status, including completed and failed, and
              outside the repo view so it survives a tab switch. The panel
              manages its own dismissal (close button + auto-hide). */}
          {ingestionJob && <IngestionStatus />}

          {!isFullscreen && selectedNode && !selectedEdge && (
            isModuleGroup(selectedNode) ? <ModuleDetailsDrawer /> : <NodeDetailsDrawer />
          )}
          {!isFullscreen && selectedEdge && !selectedNode && <EdgeDetailsDrawer />}
        </div>
      </div>
      <AuthModal />
    </ErrorBoundary>
  );
}

export default function App() {
  return <HomePage />;
}