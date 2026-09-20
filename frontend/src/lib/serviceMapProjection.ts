import type { ServiceMapEdge, ServiceMapNode, ServiceMapResponse } from "./types.ts";
import { serviceMapForces } from "./serviceMapLayout.ts";
import { isolateBlock } from "./serviceMapIsolateBlock.ts";
import { MAX_SERVICE_LABEL_PX } from "./serviceMapLabel.ts";

export interface ServiceMapProjection {
  nodes: ServiceMapNode[];
  links: (ServiceMapEdge & { id: string })[];
  dangling: number;
  isolated: number;
}

export interface ServiceMapEmptyState {
  title: string;
  detail: string;
}

/* react-force-graph mutates the graph object it is handed, so every call
 * returns its own arrays rather than sharing a module-level empty one. */
function nothingToDraw(): ServiceMapProjection {
  return { nodes: [], links: [], dangling: 0, isolated: 0 };
}

/** How wide the canvas is assumed to be when the caller does not say.
 *
 * Only the picker leaves it out, and it reads node and link COUNTS, which no
 * isolate position can change. The canvas itself always passes its real width,
 * because how many names fit across it is the whole question. */
const ASSUMED_CANVAS_PX = 900;

function nodeInScope(node: ServiceMapNode, scopeRepoIds: string[]): boolean {
  if (scopeRepoIds.length === 0) return true;
  const ids = node.repo_ids ?? [];
  // Repo-less rendezvous nodes remain until edge pruning; BUILT_FROM
  // bookkeeping does not become the visual centre of the architecture.
  if (ids.length === 0) return true;
  return ids.some((id) => scopeRepoIds.includes(id));
}

function builtFromScope(node: ServiceMapNode, scopeRepoIds: string[]): boolean {
  if (scopeRepoIds.length === 0) return true;
  return (node.repo_ids ?? []).some((id) => scopeRepoIds.includes(id));
}

function edgeInScope(edge: ServiceMapEdge, scopeRepoIds: string[]): boolean {
  if (scopeRepoIds.length === 0) return true;
  // Repo-less endpoints need edge attribution to avoid leaking another scope.
  if (!edge.source_repo_id) return true;
  return scopeRepoIds.includes(edge.source_repo_id);
}

/** What the canvas knows and the projection cannot work out for itself. */
export interface ServiceMapViewport {
  canvasWidthPx: number;
}

export function projectServiceMap(
  data: ServiceMapResponse | null,
  mapEdgeTypes: string[],
  scopeRepoIds: string[],
  viewport?: ServiceMapViewport,
): ServiceMapProjection {
  if (!data) return nothingToDraw();

  const scopedNodes = data.nodes.filter((node) => nodeInScope(node, scopeRepoIds));
  const scopedIds = new Set(scopedNodes.map((node) => node.id));
  const allIds = new Set(data.nodes.map((node) => node.id));

  const selected = data.edges.filter(
    (edge) => edge.type !== "BUILT_FROM" && mapEdgeTypes.includes(edge.type),
  );
  const links = selected
    .filter((edge) => edgeInScope(edge, scopeRepoIds))
    .filter((edge) => scopedIds.has(edge.source) && scopedIds.has(edge.target))
    .map((edge) => ({ ...edge, id: `${edge.source}->${edge.target}->${edge.type}` }));
  // Scope filtering is not a dangling-edge data error.
  const dangling = selected.filter(
    (edge) => !allIds.has(edge.source) || !allIds.has(edge.target),
  ).length;

  const connected = new Set<string>();
  for (const link of links) {
    connected.add(typeof link.source === "object" ? link.source.id : link.source);
    connected.add(typeof link.target === "object" ? link.target.id : link.target);
  }

  const retained = scopedNodes.filter((node) => {
    if (connected.has(node.id)) return true;
    if (node.kind !== "service") return false;
    return builtFromScope(node, scopeRepoIds);
  });
  const isolates = retained.filter((node) => !connected.has(node.id));
  const isolateIndex = new Map(isolates.map((node, index) => [node.id, index]));
  const placements = isolateBlock({
    count: isolates.length,
    nodeCount: retained.length,
    linkDistance: serviceMapForces(retained.length).linkDistance,
    canvasWidthPx: viewport?.canvasWidthPx ?? ASSUMED_CANVAS_PX,
    labelBudgetPx: MAX_SERVICE_LABEL_PX,
  });
  const nodes = retained.map((node) => {
    const index = isolateIndex.get(node.id);
    if (index == null) return { ...node };
    return { ...node, ...placements[index] };
  });

  return { nodes, links, dangling, isolated: isolates.length };
}

/**
 * Why the canvas has nothing to draw, or null when it does. A blank map is
 * indistinguishable from a failed one, and the two have opposite remedies:
 * an estate with no resolved services needs ingestion, a scope that excludes
 * every resolved service needs a wider scope.
 */
export function serviceMapEmptyState(
  data: ServiceMapResponse | null,
  projection: ServiceMapProjection,
  scopeRepoIds: string[],
): ServiceMapEmptyState | null {
  if (!data || projection.nodes.length > 0) return null;

  const services = data.nodes.filter((node) => node.kind === "service").length;
  if (services === 0) {
    return {
      title: "No services resolved",
      detail: "Linking found no service boundaries in the ingested repositories, "
        + "so the map has nothing to draw.",
    };
  }
  const plural = services === 1 ? "" : "s";
  return {
    title: "No services in this scope",
    detail: `Linking resolved ${services} service${plural} elsewhere in the estate, `
      + `none of them attributed to the selected ${scopeRepoIds.length === 1 ? "repository" : "repositories"}. `
      + "Widen the repository scope to see them.",
  };
}
