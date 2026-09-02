import {
  GraphResponse, RepoSummary, JobStatus, SearchResult,
  NodeDetail, IngestRepoRequest, ServiceMapResponse, TraceResponse, LinkerStatus,
  ClientConfig,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

// The API token is a single unscoped credential with full read+write over the
// whole graph. sessionStorage confines it to the tab and clears it on close;
// localStorage would leave it readable by any future XSS indefinitely. Any
// value previously persisted to localStorage is migrated out and erased.
const TOKEN_KEY = "api_token";

function readStoredToken(): string {
  if (typeof window === "undefined") return "";
  const legacy = window.localStorage.getItem(TOKEN_KEY);
  if (legacy) {
    window.localStorage.removeItem(TOKEN_KEY);
    window.sessionStorage.setItem(TOKEN_KEY, legacy);
    return legacy;
  }
  return window.sessionStorage.getItem(TOKEN_KEY) || "";
}

let apiToken = readStoredToken();

export function setApiToken(token: string) {
  apiToken = token;
  if (typeof window === "undefined") return;
  if (token) {
    window.sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    window.sessionStorage.removeItem(TOKEN_KEY);
  }
}

export function clearApiToken() {
  setApiToken("");
}

export function getApiToken() {
  return apiToken;
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string> | undefined),
  };
  
  if (apiToken) {
    headers["Authorization"] = `Bearer ${apiToken}`;
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401) {
      if (typeof window !== "undefined") window.dispatchEvent(new Event("auth-required"));
    }
    const body = await response.text();
    // Carry the status on the error. Without it callers cannot tell a bad
    // token (401) from a server with no token configured (503) from a
    // backend that cannot reach Neo4j (500) — which is how a database
    // outage came to be reported to the user as "invalid API token".
    const error = new Error(body || `API error ${response.status}`) as ApiError;
    error.status = response.status;
    error.body = body;
    throw error;
  }

  return response.json();
}

export interface ApiError extends Error {
  /** HTTP status, absent when the request never reached the server. */
  status?: number;
  body?: string;
}

export const api = {
  health: () => fetchJson<{ status: string; neo4j: string }>(`${API_BASE}/health`),

  ingestRepo: (req: IngestRepoRequest) =>
    fetchJson<{ job_id: string; repo_id: string; status: string; message: string }>(
      `${API_BASE}/api/repos/ingest`,
      { method: "POST", body: JSON.stringify(req) }
    ),

  listRepos: () =>
    fetchJson<{ repos: RepoSummary[] }>(`${API_BASE}/api/repos`),

  getRepo: (repoId: string) =>
    fetchJson<RepoSummary>(`${API_BASE}/api/repos/${repoId}`),

  deleteRepo: (repoId: string) =>
    fetch(`${API_BASE}/api/repos/${repoId}`, {
      method: "DELETE",
      headers: apiToken ? { "Authorization": `Bearer ${apiToken}` } : {}
    }),

  refreshRepo: (repoId: string) =>
    fetchJson<{ job_id: string; repo_id: string; status: string; message: string }>(
      `${API_BASE}/api/repos/${repoId}/refresh`,
      { method: "POST" }
    ),

  getJobStatus: (jobId: string) =>
    fetchJson<JobStatus>(`${API_BASE}/api/jobs/${jobId}`),

  getGraph: (repoId: string, params?: {
    view?: string;
    node_types?: string;
    edge_types?: string;
    search?: string;
    limit?: number;
    focus_node_id?: string;
    depth?: number;
  }) => {
    const queryParams = new URLSearchParams();
    if (params?.view) queryParams.set("view", params.view);
    if (params?.node_types) queryParams.set("node_types", params.node_types);
    if (params?.edge_types) queryParams.set("edge_types", params.edge_types);
    if (params?.search) queryParams.set("search", params.search);
    if (params?.limit) queryParams.set("limit", String(params.limit));
    if (params?.focus_node_id) queryParams.set("focus_node_id", params.focus_node_id);
    if (params?.depth) queryParams.set("depth", String(params.depth));

    return fetchJson<GraphResponse>(
      `${API_BASE}/api/repos/${repoId}/graph?${queryParams.toString()}`
    );
  },

  searchNodes: (repoId: string, query: string) =>
    fetchJson<{ results: SearchResult[] }>(
      `${API_BASE}/api/repos/${repoId}/search?q=${encodeURIComponent(query)}`
    ),

  getNodeDetails: (repoId: string, nodeId: string) =>
    fetchJson<NodeDetail>(`${API_BASE}/api/repos/${repoId}/nodes/${encodeURIComponent(nodeId)}`),

  getNeighbors: (repoId: string, nodeId: string, depth?: number) =>
    fetchJson<{ neighbors: Array<{ id: string; type: string; label: string; path?: string; distance: number }>; count: number }>(
      `${API_BASE}/api/repos/${repoId}/nodes/${encodeURIComponent(nodeId)}/neighbors?depth=${depth || 1}`
    ),

  rebuildLinks: () => 
    fetchJson<{ job_id: string; status: string }>(`${API_BASE}/api/v2/links/rebuild`, { method: "POST" }),
  
  getLinkerStatus: () => 
    fetchJson<LinkerStatus>(`${API_BASE}/api/v2/links/status`),

  getCodeBridges: (repoIds: string[]) =>
    fetchJson<{ nodes: any[]; links: any[]; repos: string[] }>(
      `${API_BASE}/api/v2/code-bridges?repos=${encodeURIComponent(repoIds.join(","))}`),

  getClientConfig: () =>
    fetchJson<ClientConfig>(
      `${API_BASE}/api/config`),
  
  getServiceMap: (minConfidence: number = 0.6, limit: number = 500) => 
    fetchJson<ServiceMapResponse>(`${API_BASE}/api/v2/service-map?min_confidence=${minConfidence}&limit=${limit}`),
  
  getTrace: (from: string, to: string, minConfidence: number, maxHops: number, k: number, altitude: string) => 
    fetchJson<TraceResponse>(`${API_BASE}/api/v2/trace?from_service=${encodeURIComponent(from)}&to_service=${encodeURIComponent(to)}&min_confidence=${minConfidence}&max_hops=${maxHops}&k=${k}&altitude=${altitude}`)
};
