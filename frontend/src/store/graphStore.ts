import { create } from "zustand";
import {
  GraphNode, GraphLink, GraphStats, RepoSummary,
  NodeDetail, ViewMode, JobStatus, ServiceMapResponse, TraceResponse, LinkerStatus,
  ClientConfig,
} from "@/lib/types";

type AppMode = "repo" | "service_map" | "trace";

interface GraphState {
  appMode: AppMode;
  setAppMode: (mode: AppMode) => void;
  mapEdgeTypes: string[];
  toggleMapEdgeType: (type: string) => void;

  selectedRepo: RepoSummary | null;
  repos: RepoSummary[];
  setSelectedRepo: (repo: RepoSummary | null) => void;

  // Empty scope means all repositories in every workspace.
  scopeRepoIds: string[];
  toggleScopeRepo: (repoId: string) => void;
  setScopeRepos: (repoIds: string[]) => void;

  traceFrom: string;
  traceTo: string;
  setTraceEndpoints: (from: string, to: string) => void;

  // Edge types to EMPHASISE. Distinct from `filteredEdgeTypes`, which removes
  // them: filtering answers "show me only these" by deleting the structure
  // that made them meaningful, highlighting answers "where are these?" while
  // keeping it. The two compose -- filter decides what exists, highlight
  // decides what stands out.
  highlightedEdgeTypes: string[];
  toggleHighlightEdgeType: (type: string) => void;
  clearHighlightedEdgeTypes: () => void;

  // A node the user asked to see that the capped sample did not include.
  // Set from a search result; the canvas reloads around it.
  focusNodeId: string | null;
  focusNodeRepo: string | null;
  setFocusNode: (nodeId: string | null, repoId?: string | null) => void;

  // Repo tab, multi-repo: hide each codebase's internals and show only the
  // tissue that joins them. The connections are why you selected two repos.
  connectionsOnly: boolean;
  setConnectionsOnly: (on: boolean) => void;
  // How many cross-repo bridges the current selection has, so the canvas can
  // say "these repos do not touch" instead of drawing silent islands.
  bridgeCount: number;
  setBridgeCount: (n: number) => void;
  bridgeStatus: "idle" | "loading" | "ready" | "unavailable";
  setBridgeStatus: (status: GraphState["bridgeStatus"]) => void;

  clientConfig: ClientConfig | null;
  setClientConfig: (c: ClientConfig) => void;
  setRepos: (repos: RepoSummary[]) => void;
  addRepo: (repo: RepoSummary) => void;

  nodes: GraphNode[];
  links: GraphLink[];
  stats: GraphStats | null;
  setGraphData: (nodes: GraphNode[], links: GraphLink[], stats: GraphStats) => void;
  loadingGraph: boolean;
  setLoadingGraph: (loading: boolean) => void;

  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  filteredNodeTypes: string[];
  setFilteredNodeTypes: (types: string[] | ((prev: string[]) => string[])) => void;
  filteredEdgeTypes: string[];
  setFilteredEdgeTypes: (types: string[] | ((prev: string[]) => string[])) => void;

  selectedNode: GraphNode | null;
  selectedNodeDetails: NodeDetail | null;
  setSelectedNode: (node: GraphNode | null) => void;
  setSelectedNodeDetails: (details: NodeDetail | null) => void;

  selectedEdge: any | null;
  setSelectedEdge: (edge: any | null) => void;

  searchQuery: string;
  setSearchQuery: (query: string) => void;
  showLabels: boolean;
  setShowLabels: (show: boolean) => void;
  toggleShowLabels: () => void;
  showParticles: boolean;
  setShowParticles: (show: boolean) => void;
  isFullscreen: boolean;
  setIsFullscreen: (fs: boolean) => void;

  ingestionJob: JobStatus | null;
  setIngestionJob: (job: JobStatus | null) => void;

  error: string | null;
  setError: (error: string | null) => void;

  serviceMapData: ServiceMapResponse | null;
  setServiceMapData: (data: ServiceMapResponse | null) => void;

  traceData: TraceResponse | null;
  setTraceData: (data: TraceResponse | null) => void;

  linkerStatus: LinkerStatus | null;
  setLinkerStatus: (status: LinkerStatus | null) => void;

  dimension: "2d" | "3d";
  setDimension: (dim: "2d" | "3d") => void;
  toggleDimension: () => void;
  layout3d: "atlas" | "sphere" | "layers";
  setLayout3d: (l: "atlas" | "sphere" | "layers") => void;
  flow3d: boolean;
  toggleFlow3d: () => void;
  autoOrbit3d: boolean;
  toggleAutoOrbit3d: () => void;
  activePath3d: string[] | null;
  setActivePath3d: (path: string[] | null) => void;
  hudMode3d: "OVERVIEW" | "FOCUS" | "PATH";
  setHudMode3d: (mode: GraphState["hudMode3d"]) => void;
  hideLockfileDeps: boolean;
  toggleHideLockfileDeps: () => void;

  graphControlCallbacks: {
    resetCamera?: () => void;
    fitGraph?: () => void;
    togglePhysics?: () => void;
    rotateGraph?: () => void;
    physicsEnabled?: boolean;
  };
  setGraphControlCallbacks: (callbacks: GraphState["graphControlCallbacks"]) => void;
}

export const useGraphStore = create<GraphState>((set) => ({
  appMode: "repo",
  setAppMode: (mode) => set((state) => state.appMode === mode ? state : ({
    appMode: mode, highlightedEdgeTypes: [], selectedNode: null,
    selectedNodeDetails: null, selectedEdge: null, activePath3d: null,
    hudMode3d: "OVERVIEW", focusNodeId: null, focusNodeRepo: null,
    searchQuery: "",
  })),
  mapEdgeTypes: ["ROUTES_TO", "CALLS_SERVICE", "PUBLISHES_TO", "CONSUMES_FROM", "FANS_OUT_TO"],
  toggleMapEdgeType: (type) =>
    set((state) => ({
      mapEdgeTypes: state.mapEdgeTypes.includes(type)
        ? state.mapEdgeTypes.filter((t) => t !== type)
        : [...state.mapEdgeTypes, type],
    })),

  selectedRepo: null,
  repos: [],
  setSelectedRepo: (repo) => set({ selectedRepo: repo }),

  scopeRepoIds: [],
  toggleScopeRepo: (repoId) =>
    set((state) => ({
      scopeRepoIds: state.scopeRepoIds.includes(repoId)
        ? state.scopeRepoIds.filter((id) => id !== repoId)
        : [...state.scopeRepoIds, repoId],
      selectedNode: null, selectedEdge: null, focusNodeId: null,
      focusNodeRepo: null, activePath3d: null, traceData: null, searchQuery: "",
    })),
  setScopeRepos: (scopeRepoIds) => set((state) =>
    state.scopeRepoIds.join(",") === scopeRepoIds.join(",")
      ? state
      : {
          scopeRepoIds, selectedNode: null, selectedNodeDetails: null,
          selectedEdge: null, focusNodeId: null, focusNodeRepo: null,
          activePath3d: null, traceData: null, traceFrom: "", traceTo: "",
          searchQuery: "",
        }),

  traceFrom: "",
  traceTo: "",
  setTraceEndpoints: (traceFrom, traceTo) => set((state) =>
    state.traceFrom === traceFrom && state.traceTo === traceTo
      ? state
      : { traceFrom, traceTo, traceData: null, selectedEdge: null }),

  highlightedEdgeTypes: [],
  toggleHighlightEdgeType: (type) =>
    set((state) => ({
      highlightedEdgeTypes: state.highlightedEdgeTypes.includes(type)
        ? state.highlightedEdgeTypes.filter((t) => t !== type)
        : [...state.highlightedEdgeTypes, type],
    })),
  clearHighlightedEdgeTypes: () => set({ highlightedEdgeTypes: [] }),

  focusNodeId: null,
  focusNodeRepo: null,
  setFocusNode: (nodeId, repoId = null) =>
    set({ focusNodeId: nodeId, focusNodeRepo: repoId }),

  connectionsOnly: false,
  setConnectionsOnly: (on) => set({ connectionsOnly: on }),
  bridgeCount: 0,
  setBridgeCount: (n) => set({ bridgeCount: n }),
  bridgeStatus: "idle",
  setBridgeStatus: (bridgeStatus) => set({ bridgeStatus }),

  clientConfig: null,
  setClientConfig: (c) => set({ clientConfig: c }),
  setRepos: (repos) => set({ repos }),
  addRepo: (repo) => set((state) => ({ repos: [repo, ...state.repos] })),

  nodes: [],
  links: [],
  stats: null,
  setGraphData: (nodes, links, stats) => set((state) => {
    const selected = state.selectedNode
      ? nodes.find((node) => node.id === state.selectedNode?.id) ?? null
      : null;
    return { nodes, links, stats, selectedNode: selected, selectedEdge: null };
  }),
  loadingGraph: false,
  setLoadingGraph: (loading) => set({ loadingGraph: loading }),

  viewMode: "overview",
  setViewMode: (mode) => set({ viewMode: mode }),
  filteredNodeTypes: [],
  setFilteredNodeTypes: (types) => set((state) => ({
    filteredNodeTypes: typeof types === "function" ? types(state.filteredNodeTypes) : types,
  })),
  filteredEdgeTypes: [],
  setFilteredEdgeTypes: (types) => set((state) => ({
    filteredEdgeTypes: typeof types === "function" ? types(state.filteredEdgeTypes) : types,
  })),

  selectedNode: null,
  selectedNodeDetails: null,
  setSelectedNodeDetails: (details) => set({ selectedNodeDetails: details }),
  // `selectedEdge: undefined` here is what made the edge drawer unreachable:
  // every view calls `setSelectedEdge(link); setSelectedNode(null)`, and
  // zustand's Object.assign copies an explicit `undefined` over the edge that
  // was just selected. App.tsx then gates on `selectedEdge &&` and never
  // renders. Clearing the *other* selection only when a node is actually
  // being selected is the whole fix.
  setSelectedNode: (node) =>
    set(node
      ? { selectedNode: node, selectedNodeDetails: null, selectedEdge: null,
          activePath3d: null, hudMode3d: "FOCUS" }
      : { selectedNode: null, selectedNodeDetails: null }),

  selectedEdge: null,
  setSelectedEdge: (edge) => set((state) => ({ 
    selectedEdge: edge, 
    selectedNode: edge ? null : state.selectedNode 
  })),

  searchQuery: "",
  setSearchQuery: (query) => set({ searchQuery: query }),
  showLabels: true,
  setShowLabels: (show) => set({ showLabels: show }),
  toggleShowLabels: () => set((state) => ({ showLabels: !state.showLabels })),
  showParticles: false,
  setShowParticles: (show) => set({ showParticles: show }),
  isFullscreen: false,
  setIsFullscreen: (fs) => set({ isFullscreen: fs }),

  ingestionJob: null,
  setIngestionJob: (job) => set({ ingestionJob: job }),

  error: null,
  setError: (error) => set({ error }),

  serviceMapData: null,
  setServiceMapData: (data) => set({ serviceMapData: data }),

  traceData: null,
  setTraceData: (data) => set({ traceData: data, selectedEdge: null }),

  linkerStatus: null,
  setLinkerStatus: (status) => set({ linkerStatus: status }),

  dimension: "2d",
  setDimension: (dim) => set({ dimension: dim }),
  toggleDimension: () => set((state) => ({ dimension: state.dimension === "2d" ? "3d" : "2d" })),
  layout3d: "atlas",
  setLayout3d: (layout3d) => set({ layout3d }),
  flow3d: false,
  toggleFlow3d: () => set((state) => ({ flow3d: !state.flow3d })),
  autoOrbit3d: false,
  toggleAutoOrbit3d: () => set((state) => ({ autoOrbit3d: !state.autoOrbit3d })),
  activePath3d: null,
  setActivePath3d: (path) => set((state) => ({
    activePath3d: path,
    hudMode3d: path?.length ? "PATH" : state.selectedNode ? "FOCUS" : "OVERVIEW",
  })),
  hudMode3d: "OVERVIEW",
  setHudMode3d: (mode) => set({ hudMode3d: mode }),
  hideLockfileDeps: true,
  toggleHideLockfileDeps: () => set((state) => ({ hideLockfileDeps: !state.hideLockfileDeps })),

  graphControlCallbacks: {},
  setGraphControlCallbacks: (callbacks) => set({ graphControlCallbacks: callbacks }),
}));
