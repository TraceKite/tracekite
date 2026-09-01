export const NODE_COLORS: Record<string, string> = {
  ModuleGroup: "#315b47",
  Repo: "#a45138",
  Folder: "#315b47",
  File: "#8a8e84",
  Package: "#9b7a31",
  Class: "#4b5148",
  Interface: "#6b5f4f",
  Method: "#49705d",
  Function: "#49705d",
  component: "#49705d",
  ApiEndpoint: "#a45138",
  Dependency: "#9b7a31",
  Config: "#756342",
  ExternalSystem: "#8b4d39",
  ExternalApi: "#8b4d39",
  Test: "#6b6f65",
  DockerResource: "#3c4038",
  KubernetesResource: "#3c4038",
  ContractClaim: "#a45138",
  HttpContract: "#a45138",
  ContractOperation: "#9b7a31",
  Topic: "#315b47",
  Library: "#756342",
};

export const NODE_SIZES: Record<string, number> = {
  ModuleGroup: 2.4,
  Repo: 1.5, Folder: 1.1, File: 0.75, Package: 0.9, Class: 0.9, Interface: 0.85,
  Method: 0.55, Function: 0.55, component: 0.8, ApiEndpoint: 1.0, Dependency: 0.75,
  Config: 0.65, ExternalSystem: 1.1, ExternalApi: 0.9, Test: 0.7, DockerResource: 0.9, KubernetesResource: 0.9,
};

export const EDGE_COLORS: Record<string, string> = {
  AGGREGATE: "#6b6f65",
  CONTAINS: "#6b6f65", DECLARES: "#6b6f65", IMPORTS: "#8a8e84", CALLS: "#315b47",
  IMPLEMENTS: "#756342", EXTENDS: "#756342", EXPOSES_API: "#a45138", CALLS_API: "#a45138",
  USES_CONFIG: "#756342", CONFIGURED_BY: "#756342", DEPENDS_ON: "#9b7a31", READS_FROM: "#315b47",
  WRITES_TO: "#a45138", TESTED_BY: "#8a8e84",
  RELATED_TO: "#6b6f65", CALLS_SERVICE: "#315b47", ROUTES_TO: "#a45138", BUILT_FROM: "#6b6f65",
  PUBLISHES_TO: "#a45138",
  CONSUMES_FROM: "#315b47",
  FANS_OUT_TO: "#9b7a31",
  INVOKES: "#a45138",
  EXPOSES: "#a45138",
};

/** Edge types that cross a repository boundary. */
export const CROSSING_EDGE_TYPES = new Set(["INVOKES", "EXPOSES"]);

export function isCrossingEdge(edgeType: string): boolean {
  return CROSSING_EDGE_TYPES.has(edgeType);
}

const MODULE_HUES = [
  "#315b47",
  "#a45138",
  "#9b7a31",
  "#6b5f4f",
  "#49705d",
  "#8b4d39",
  "#756342",
  "#8a8e84",
];

/** The module a path belongs to. Mirrors `module_of` in the API. */
const MODULE_CONTAINERS = new Set(["projects", "services", "apps", "packages",
                                   "modules", "libs", "components", "cmd", "src"]);
const INFRASTRUCTURE_DIRS = new Set([
  "deploy", "deployment", "deployments", "docker", "dockerfiles", "k8s",
  "kubernetes", "kube", "manifests", "manifest", "chart", "charts", "helm",
  "helmfile", "kustomize", "overlays", "infra", "infrastructure", "terraform",
  "tf", "ansible", "ops", "argocd", "flux", "skaffold", "compose", "ci",
  "build", "scripts", "config", "configs", "etc", "env", "environments",
  ".github", ".gitlab", ".circleci",
]);

export function moduleOf(path: string | null | undefined): string {
  const parts = (path || "").split("/").filter(Boolean);
  if (parts.length < 2) return "";
  if (MODULE_CONTAINERS.has(parts[0]) && parts.length > 2) {
    return `${parts[0]}/${parts[1]}`;
  }
  if (INFRASTRUCTURE_DIRS.has(parts[0].toLowerCase())) return "";
  return parts[0];
}

export function graphGroupOf(node: GraphNode): string {
  const enriched = node as GraphNode & { repo_id?: string; module?: string };
  const inferred = enriched.module ?? moduleOf(node.path);
  const rootFolder = node.type === "Folder" && node.path && !node.path.includes("/") &&
    !node.path.startsWith(".") ? node.path : "";
  const structuralRoot = (node.type === "Folder" || node.type === "File") ? "root" : "";
  const moduleKey = inferred || rootFolder || structuralRoot || node.group || node.type;
  const rawRepo = enriched.repo_id?.split("/").pop();
  const divider = rawRepo?.lastIndexOf("_") ?? -1;
  const repoKey = rawRepo && divider > 0
    ? `${rawRepo.slice(0, divider).replaceAll("_", "-")}/${rawRepo.slice(divider + 1)}`
    : rawRepo;
  return repoKey && moduleKey ? `${repoKey}/${moduleKey}` : moduleKey || repoKey || "core";
}

export function getModuleColor(moduleKey: string | null | undefined,
                              order: string[]): string | null {
  if (!moduleKey || order.length < 2) return null;
  const index = order.indexOf(moduleKey);
  return index < 0 ? null : MODULE_HUES[index % MODULE_HUES.length];
}

export const MODULE_HUE_LIST = MODULE_HUES;

export const MAP_EDGE_LEGEND: { type: string; label: string }[] = [
  { type: "ROUTES_TO", label: "Gateway route" },
  { type: "CALLS_SERVICE", label: "Service call" },
  { type: "PUBLISHES_TO", label: "Publishes to topic" },
  { type: "CONSUMES_FROM", label: "Consumes from topic" },
  { type: "FANS_OUT_TO", label: "Topic fan-out" },
];

export const EDGE_WIDTHS: Record<string, number> = {
  CONTAINS: 0.8, DECLARES: 0.8, IMPORTS: 1.1, CALLS: 1.5, IMPLEMENTS: 1.0, EXTENDS: 1.0,
  EXPOSES_API: 1.6, CALLS_API: 1.5, USES_CONFIG: 1.0, CONFIGURED_BY: 1.0, DEPENDS_ON: 1.0,
  READS_FROM: 1.2, WRITES_TO: 1.2, PUBLISHES_TO: 1.4, CONSUMES_FROM: 1.4, TESTED_BY: 0.9, RELATED_TO: 0.6,
  CALLS_SERVICE: 1.8, ROUTES_TO: 1.8, BUILT_FROM: 0.8,
};

export function getNodeColor(nodeType: string): string {
  return NODE_COLORS[nodeType] || "#8a8e84";
}

export function getNodeSize(nodeType: string, baseSize: number = 4): number {
  const multiplier = NODE_SIZES[nodeType] || 1;
  return Math.min(baseSize * multiplier, 14);
}

export function getEdgeColor(edgeType: string): string {
  return EDGE_COLORS[edgeType] || "#8a8e84";
}

export function getEdgeWidth(edgeType: string): number {
  if (isCrossingEdge(edgeType)) return 2.2;
  return EDGE_WIDTHS[edgeType] || 0.6;
}

export const CONFIDENCE_BANDS = [
  { min: 0.9, label: "High", token: "--color-success-text" },
  { min: 0.75, label: "Medium", token: "--color-text-secondary" },
  { min: 0, label: "Low", token: "--color-warning-text" },
] as const;

export function getConfidenceBand(conf: number | null) {
  if (conf === null) return { min: 0, label: "Unknown", token: "--color-neutral-text" } as const;
  return CONFIDENCE_BANDS.find((band) => conf >= band.min) ?? CONFIDENCE_BANDS[2];
}

export function getConfidenceStyle(confidence: number | null): { opacity: number; dash: number[] } {
  if (confidence === null) return { opacity: 0.8, dash: [] };
  if (confidence >= 0.9) return { opacity: 0.95, dash: [] };
  if (confidence >= 0.75) return { opacity: 0.85, dash: [] };
  return { opacity: 0.75, dash: [5, 3] };
}

export function formatConfidence(conf: number | null): string {
  if (conf === null) return "Unknown";
  return `${getConfidenceBand(conf).label} · ${conf.toFixed(2)}`;
}

export function getConfidenceColor(conf: number | null): string {
  if (conf === null) return "#8a8e84";
  if (conf >= 0.9) return "#315b47";
  if (conf >= 0.75) return "#6b6f65";
  return "#9b7a31";
}

export const SCENE_BACKGROUND = "#fbfaf6";
export const PARTICLE_COLOR = "#252821";

export function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? { r: parseInt(result[1], 16) / 255, g: parseInt(result[2], 16) / 255, b: parseInt(result[3], 16) / 255 } : { r: 0.5, g: 0.5, b: 0.5 };
}

export function getColorLuminance(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const toLinear = (c: number) => c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

export function getAdaptiveLabelStyle(nodeColor: string) {
  return {
    pillFill: "rgba(255, 254, 250, 0.96)",
    textFill: "#252821",
    textStroke: "rgba(255, 254, 250, 0.85)",
    borderColor: nodeColor,
  };
}
import type { GraphNode } from "@/lib/types";
