import { create } from "zustand";
import {
  GraphNode, GraphLink, GraphStats, RepoSummary,
  NodeDetail, ViewMode, JobStatus, ServiceMapResponse, TraceResponse, LinkerStatus
} from "@/lib/types";

type AppMode = "repo" | "service_map" | "trace";

interface GraphState {
  appMode: AppMode;
  setAppMode: (mode: AppMode) => void;
  // Which edge types the service map draws. Superimposing routing, calls and
  // messaging on one canvas is a documented failure mode — they are different
  // relations and deserve to be separable.
  mapEdgeTypes: string[];
  toggleMapEdgeType: (type: string) => void;

  selectedRepo: RepoSummary | null;
  repos: RepoSummary[];
  setSelectedRepo: (repo: RepoSummary | null) => void;

  // Scope vs focus. `selectedRepo` is the FOCUS: the one repo the Repo tab
  // renders internals for. `scopeRepoIds` is the SCOPE: which repos the
  // cross-repo views (Service Map, Trace) consider. Overloading one field for
  // both is why the dropdown looked like a global filter while Service Map and
  // Trace ignored it entirely. Empty means "all repos".
  scopeRepoIds: string[];
  toggleScopeRepo: (repoId: string) => void;
  setScopeRepos: (repoIds: string[]) => void;

  // Trace endpoints live here rather than inside TraceView so the Service Map
  // can hand off to them: selecting a service and choosing "trace from here"
  // is what makes Trace the second step of one flow instead of a rival view.
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

  clientConfig: { max_scope_repos: number; service_map_edge_limit: number } | null;
  setClientConfig: (c: { max_scope_repos: number; service_map_edge_limit: number }) => void;
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
  // Switching view clears any highlight. The two canvases share this state but
  // NOT their edge vocabularies -- they overlap on 2 of 20 types -- so carrying
  // a highlight across would dim every edge in the destination view, with a
  // "Clear highlight" control naming a type absent from its own list. Same
  // fault as leaving a highlight on a hidden type: the canvas looks broken and
  // says nothing. A highlight is a transient investigation, not a preference.
  setAppMode: (mode) => set({ appMode: mode, highlightedEdgeTypes: [] }),
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
    })),
  setScopeRepos: (repoIds) => set({ scopeRepoIds: repoIds }),

  traceFrom: "",
  traceTo: "",
  setTraceEndpoints: (from, to) => set({ traceFrom: from, traceTo: to }),

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

  clientConfig: null,
  setClientConfig: (c) => set({ clientConfig: c }),
  setRepos: (repos) => set({ repos }),
  addRepo: (repo) => set((state) => ({ repos: [repo, ...state.repos] })),

  nodes: [],
  links: [],
  stats: null,
  setGraphData: (nodes, links, stats) => set({ nodes, links, stats, selectedNode: null, selectedEdge: null }),
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
      ? { selectedNode: node, selectedNodeDetails: null, selectedEdge: null }
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
  showParticles: true,
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
  setTraceData: (data) => set({ traceData: data }),

  linkerStatus: null,
  setLinkerStatus: (status) => set({ linkerStatus: status }),

  graphControlCallbacks: {},
  setGraphControlCallbacks: (callbacks) => set({ graphControlCallbacks: callbacks }),
}));