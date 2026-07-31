export const NODE_COLORS: Record<string, string> = {
  Repo: "#f59e0b",
  Folder: "#38bdf8",
  File: "#aab2bb",
  Package: "#22d3ee",
  Class: "#a78bfa",
  Interface: "#f472b6",
  Method: "#4ade80",
  Function: "#34d399",
  component: "#fb923c",
  ApiEndpoint: "#f87171",
  Dependency: "#facc15",
  Config: "#2dd4bf",
  ExternalSystem: "#f43f5e",
  ExternalApi: "#fb7185",
  Test: "#a3e635",
  DockerResource: "#60a5fa",
  KubernetesResource: "#818cf8",
};

export const NODE_SIZES: Record<string, number> = {
  Repo: 1.5, Folder: 1.1, File: 0.75, Package: 0.9, Class: 0.9, Interface: 0.85,
  Method: 0.55, Function: 0.55, component: 0.8, ApiEndpoint: 1.0, Dependency: 0.75,
  Config: 0.65, ExternalSystem: 1.1, ExternalApi: 0.9, Test: 0.7, DockerResource: 0.9, KubernetesResource: 0.9,
};

export const EDGE_COLORS: Record<string, string> = {
  CONTAINS: "#aab2bb", DECLARES: "#a5b4fc", IMPORTS: "#60a5fa", CALLS: "#4ade80",
  IMPLEMENTS: "#c084fc", EXTENDS: "#e879f9", EXPOSES_API: "#fb923c", CALLS_API: "#f472b6",
  USES_CONFIG: "#2dd4bf", CONFIGURED_BY: "#14b8a6", DEPENDS_ON: "#fbbf24", READS_FROM: "#a78bfa",
  WRITES_TO: "#818cf8", TESTED_BY: "#a3e635",
  RELATED_TO: "#9ca3af", CALLS_SERVICE: "#7aaeff", ROUTES_TO: "#4ade80", BUILT_FROM: "#fbbf24",
  // PUBLISHES_TO and CONSUMES_FROM were #f87171 and #fb7185 — two reds a
  // human cannot tell apart, on the two edge types whose whole point is
  // direction. FANS_OUT_TO had no entry at all and fell back to the same
  // blue as CALLS_SERVICE, so a topic fan-out looked like a direct call.
  PUBLISHES_TO: "#f5b33c",
  CONSUMES_FROM: "#5eead4",
  FANS_OUT_TO: "#c4b5fd",
  // Cross-repository crossings. INVOKES and EXPOSES had NO entry, so they
  // fell through to the #6b7280 default -- the two edge types that exist to
  // show a boundary being crossed were drawn duller than CONTAINS. One
  // reserved colour, used by nothing else, so "does a connection exist?"
  // is answerable at a glance rather than by reading labels.
  INVOKES: "#ff5cf0",
  EXPOSES: "#ff5cf0",
};

/** Edge types that cross a repository boundary. */
export const CROSSING_EDGE_TYPES = new Set(["INVOKES", "EXPOSES"]);

export function isCrossingEdge(edgeType: string): boolean {
  return CROSSING_EDGE_TYPES.has(edgeType);
}

/* Which MODULE a node belongs to, as a colour.
 *
 * Module, not repository: a repo is how code is stored, a module is what owns
 * behaviour. A monorepo holds many services, so keying on repo id would paint
 * an entire estate one colour and hide every boundary inside it.
 *
 * Applied to NODES, never to edges: an edge spans two modules and has no
 * single identity to encode, whereas colouring the endpoints makes any line
 * between two hues self-evidently a crossing. Edge colour is therefore free
 * to carry the RELATIONSHIP, and the encodings never compete.
 *
 * Hues stay clear of the crossing magenta above.
 */
const MODULE_HUES = ["#38bdf8", "#4ade80", "#facc15", "#fb923c", "#c084fc",
                     "#2dd4bf", "#f472b6", "#a3e635", "#818cf8", "#fbbf24"];

/** The module a path belongs to. Mirrors `module_of` in the API. */
const MODULE_CONTAINERS = new Set(["projects", "services", "apps", "packages",
                                   "modules", "libs", "components", "cmd", "src"]);

export function moduleOf(path: string | null | undefined): string {
  const parts = (path || "").split("/").filter(Boolean);
  if (parts.length === 0) return "";
  if (MODULE_CONTAINERS.has(parts[0]) && parts.length > 1) {
    return `${parts[0]}/${parts[1]}`;
  }
  return parts[0];
}

export function getModuleColor(moduleKey: string | null | undefined,
                               order: string[]): string | null {
  // One module on screen: nothing to tell apart, and the ring is noise.
  if (!moduleKey || order.length < 2) return null;
  const index = order.indexOf(moduleKey);
  return index < 0 ? null : MODULE_HUES[index % MODULE_HUES.length];
}

export const MODULE_HUE_LIST = MODULE_HUES;

// The edge types the service map draws, with the labels a legend needs.
// BUILT_FROM is deliberately absent: it is Service->Repo bookkeeping and was
// 42% of the live map, drawn as stars around the repo nodes.
export const MAP_EDGE_LEGEND: { type: string; label: string }[] = [
  { type: "ROUTES_TO", label: "Gateway route" },
  { type: "CALLS_SERVICE", label: "Service call" },
  { type: "PUBLISHES_TO", label: "Publishes to topic" },
  { type: "CONSUMES_FROM", label: "Consumes from topic" },
  { type: "FANS_OUT_TO", label: "Topic fan-out" },
];

export const EDGE_WIDTHS: Record<string, number> = {
  CONTAINS: 0.8, DECLARES: 0.8, IMPORTS: 1.3, CALLS: 1.6, IMPLEMENTS: 1.0, EXTENDS: 1.0,
  EXPOSES_API: 1.8, CALLS_API: 1.6, USES_CONFIG: 1.0, CONFIGURED_BY: 1.0, DEPENDS_ON: 1.3,
  READS_FROM: 1.2, WRITES_TO: 1.2, PUBLISHES_TO: 1.5, CONSUMES_FROM: 1.5, TESTED_BY: 1.0, RELATED_TO: 0.6,
  CALLS_SERVICE: 2.0, ROUTES_TO: 2.0, BUILT_FROM: 1.0,
};

export function getNodeColor(nodeType: string): string {
  return NODE_COLORS[nodeType] || "#aab2bb";
}

export function getNodeSize(nodeType: string, baseSize: number = 4): number {
  const multiplier = NODE_SIZES[nodeType] || 1;
  return Math.min(baseSize * multiplier, 14);
}

export function getEdgeColor(edgeType: string): string {
  return EDGE_COLORS[edgeType] || "#6b7280";
}

export function getEdgeWidth(edgeType: string): number {
  // A crossing is the rarest and most consequential edge on a multi-repo
  // canvas; width reinforces the reserved colour so it survives zooming out.
  if (isCrossingEdge(edgeType)) return 2.5;
  return EDGE_WIDTHS[edgeType] || 0.5;
}

/* Confidence encoding.
 *
 * Three rules, each fixing a measured defect:
 *
 * 1. ONE set of thresholds. `getConfidenceStyle` bucketed at 0.95/0.85 while
 *    `getConfidenceColor` bucketed at 0.95/0.80 — two encodings of the same
 *    variable that disagreed for everything between 0.80 and 0.85.
 * 2. Dash carries confidence; opacity does not. Sub-0.85 edges were drawn at
 *    0.3 alpha on a near-black canvas, which is the value-suppressing failure
 *    mode: maximally uncertain glyphs become invisible AND indistinguishable
 *    from each other. Dash is categorical, colourblind-safe, survives zoom,
 *    and does not compete with edge-type hue.
 * 3. Never red for low confidence. Every edge we draw is already above the
 *    linker's floor; red reads as "error" and trains the warning blindness
 *    that makes people ignore the tool. Red is reserved for `rejected`.
 */
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
  // Opacity floor 0.75: uncertain must stay legible. Uncertainty is carried
  // by the dash pattern, not by fading the edge out of existence.
  if (confidence === null) return { opacity: 0.8, dash: [] };
  if (confidence >= 0.9) return { opacity: 0.95, dash: [] };
  if (confidence >= 0.75) return { opacity: 0.85, dash: [] };
  return { opacity: 0.75, dash: [5, 3] };
}

export function formatConfidence(conf: number | null): string {
  // Band first, value second, and never one decimal place — `93.0%` is false
  // precision on a heuristic score.
  if (conf === null) return "Unknown";
  return `${getConfidenceBand(conf).label} · ${conf.toFixed(2)}`;
}

export function getConfidenceColor(conf: number | null): string {
  if (conf === null) return "#9ba3ad";
  if (conf >= 0.9) return "#4ade80";
  if (conf >= 0.75) return "#aab2bb";
  return "#f5b33c";
}

export const SCENE_BACKGROUND = "#0e1013";
export const PARTICLE_COLOR = "#3b82f6";

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
  const lum = getColorLuminance(nodeColor);
  const isBright = lum >= 0.38;
  return {
    pillFill: isBright ? "rgba(15, 23, 42, 0.92)" : "rgba(241, 245, 249, 0.95)",
    textFill: isBright ? "#f8fafc" : "#15181c",
    textStroke: isBright ? "rgba(0, 0, 0, 0.7)" : "rgba(255, 255, 255, 0.8)",
    borderColor: nodeColor,
  };
}