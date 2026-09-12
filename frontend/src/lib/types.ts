export interface RepoSummary {
  id: string;
  name: string;
  owner: string;
  repo: string;
  github_url: string;
  branch: string;
  last_ingested_at: string | null;
  ingestion_status: string;
  node_count: number;
  edge_count: number;
  head_commit_sha: string | null;
  linked_at: string | null;
  claims_by_kind: Record<string, number> | null;
  parse_coverage: Record<string, number> | null;
}

export interface ClientConfig {
  max_scope_repos: number;
  service_map_edge_limit: number;
  graph_detail_node_limit: number;
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  name: string;
  path?: string;
  repo_id?: string;
  module?: string;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
  language?: string;
  size: number;
  group: string;
  metadata: Record<string, unknown>;
}

export interface GraphLink {
  id?: string;
  source: string | any;
  target: string | any;
  type: string;
  label: string;
  value: number;
  confidence: number | null;
  aggregate?: boolean;
  member_count?: number;
  relationship_types?: string[];
}

export interface GraphStats {
  total_nodes: number;
  total_edges: number;
  node_types: Record<string, number>;
  edge_types: Record<string, number>;
  files: number;
  apis: number;
  dependencies: number;
  external_systems: number;
}

export interface GraphResponse {
  repo: RepoSummary | null;
  stats: GraphStats;
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface SearchResult {
  id: string;
  type: string;
  label: string;
  path?: string;
  score: number;
}

export interface NodeDetail {
  node: GraphNode;
  incoming: Array<{
    node_id: string;
    node_type: string;
    node_label: string;
    relationship: string;
    relationship_label: string;
  }>;
  outgoing: Array<{
    node_id: string;
    node_type: string;
    node_label: string;
    relationship: string;
    relationship_label: string;
  }>;
  neighbors: Array<{
    id: string;
    type: string;
    label: string;
    path?: string;
  }>;
  code_snippet: string | null;
}

export interface JobStatus {
  job_id: string;
  repo_id: string;
  status: string;
  progress: number;
  message: string;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface IngestRepoRequest {
  github_url: string;
  branch?: string;
  github_token?: string;
  refresh?: boolean;
}

export type ViewMode = "overview" | "architecture" | "code" | "api" | "dependencies" | "impact";

export const NODE_TYPES = [
  "Repo", "Folder", "File", "Package", "Class", "Interface",
  "Method", "ApiEndpoint", "Dependency", "Config", "ExternalSystem",
  "ExternalApi", "Test", "DockerResource", "KubernetesResource",
] as const;

export const EDGE_TYPES = [
  "CONTAINS", "DECLARES", "IMPORTS", "CALLS", "IMPLEMENTS",
  "EXTENDS", "EXPOSES_API", "CALLS_API", "USES_CONFIG", "CONFIGURED_BY",
  "DEPENDS_ON", "READS_FROM", "WRITES_TO", "PUBLISHES_TO",
  "CONSUMES_FROM", "TESTED_BY", "RELATED_TO",
] as const;

export const VIEW_MODES: ViewMode[] = [
  "overview", "architecture", "code", "api", "dependencies", "impact",
];

export interface ServiceMapNode {
  id: string;
  name: string;
  kind: "service" | "service_name" | "repo" | "node";
  is_gateway?: boolean;
  repo_ids?: string[];
  dead_end?: boolean;
  scope?: string;
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

export interface ServiceMapEdge {
  id?: string;
  source: string | any;
  target: string | any;
  type: "CALLS_SERVICE" | "ROUTES_TO" | "BUILT_FROM";
  confidence: number;
  min_confidence: number;
  max_confidence: number;
  via: string[];
  weight: number;
  path_prefix?: string;
  // Which repo the calling side was found in. Absent on edges whose source
  // carries no repo attribution, so scope filtering must not require it.
  source_repo_id?: string;
  evidence: string[];
}

export interface ServiceMapResponse {
  nodes: ServiceMapNode[];
  edges: ServiceMapEdge[];
  totals: { services: number; edges: number };
  truncated: boolean;
}

export interface TraceCrossing {
  call_site: string;
  source_path: string;
  contract: string;
  method: string;
  path_template: string;
  confidence: number;
  evidence: string[];
  claim_key: string;
}

export interface TracePath {
  nodes: ServiceMapNode[];
  edges: (ServiceMapEdge & { evidence_edge_ids?: string[] })[];
  min_confidence: number;
  crossings?: TraceCrossing[];
}

export interface TraceResponse {
  from: string;
  to: string;
  paths: TracePath[];
  altitude: "service" | "code";
  warnings: { kind: string; detail: string }[];
}

export interface LinkerWarning {
  kind: string;
  detail: string;
  repo_ids?: string[];
}

export interface LinkerRun {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  counters: Record<string, number>;
  error: string | null;
}

export interface LinkerStatus {
  runs: LinkerRun[];
  latest: LinkerRun | null;
  warnings: LinkerWarning[];
}
