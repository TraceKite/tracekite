import type { ServiceMapEdge, ServiceMapNode, ServiceMapResponse } from "./types.ts";
import { SERVICE_MAP_FRAMING, serviceMapForces } from "./serviceMapLayout.ts";
import { MAX_FIT_ZOOM } from "./graphCameraFit.ts";
import { isolateBlock } from "./serviceMapIsolateBlock.ts";
import type { GraphExtent } from "./serviceMapIsolateBlock.ts";
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
  /** Known once the canvas is measured; lets the isolate block size its cells
   * for the zoom the map will be framed at. */
  canvasHeightPx?: number;
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

  const connected = linkedIds(links);
  const retained = scopedNodes.filter((node) => {
    if (connected.has(node.id)) return true;
    if (node.kind !== "service") return false;
    return builtFromScope(node, scopeRepoIds);
  });
  const nodes = retained.map((node) => ({ ...node }));
  const isolated = nodes.filter((node) => !connected.has(node.id)).length;
  const projection = { nodes, links, dangling, isolated };
  pinIsolates(projection, viewport);
  return projection;
}

/** Ids of every node a link touches. Links arrive with string endpoints and
 * force-graph swaps them for the node objects once drawn, so both are read. */
export function linkedIds(links: readonly Pick<ServiceMapEdge, "source" | "target">[]): Set<string> {
  const ids = new Set<string>();
  for (const link of links) {
    ids.add(typeof link.source === "object" ? link.source.id : link.source);
    ids.add(typeof link.target === "object" ? link.target.id : link.target);
  }
  return ids;
}

/** Where the linked graph reaches, or null until all of it has a place. */
function graphExtent(nodes: readonly ServiceMapNode[]): GraphExtent | null {
  if (nodes.length === 0) return null;
  const extent = { left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity };
  for (const node of nodes) {
    if (node.x == null || node.y == null) return null;
    extent.left = Math.min(extent.left, node.x);
    extent.right = Math.max(extent.right, node.x);
    extent.top = Math.min(extent.top, node.y);
    extent.bottom = Math.max(extent.bottom, node.y);
  }
  return extent;
}

/**
 * Pins the isolates into their block, in place, and reports whether any moved.
 *
 * In place because force-graph owns these node objects once they are drawn,
 * and lays out any new ones from scratch — which is what every resize did while
 * the canvas width was an input to the projection. Before the layout has run
 * the block goes where the graph is expected to end; after, directly under
 * where it did.
 */
export function pinIsolates(
  projection: Pick<ServiceMapProjection, "nodes" | "links">,
  viewport?: ServiceMapViewport,
): boolean {
  const linked = linkedIds(projection.links);
  const isolates = projection.nodes.filter((node) => !linked.has(node.id));
  const placements = isolateBlock({
    count: isolates.length,
    nodeCount: projection.nodes.length,
    linkDistance: serviceMapForces(projection.nodes.length).linkDistance,
    canvasWidthPx: viewport?.canvasWidthPx ?? ASSUMED_CANVAS_PX,
    labelBudgetPx: MAX_SERVICE_LABEL_PX,
    graph: graphExtent(projection.nodes.filter((node) => linked.has(node.id))) ?? undefined,
    framing: viewport?.canvasHeightPx == null ? undefined : {
      canvasHeightPx: viewport.canvasHeightPx,
      paddingPx: SERVICE_MAP_FRAMING.padding,
      minZoom: SERVICE_MAP_FRAMING.minZoom ?? 0,
      maxZoom: MAX_FIT_ZOOM,
    },
  });
  let moved = false;
  isolates.forEach((node, index) => {
    const { fx, fy } = placements[index];
    if (node.fx === fx && node.fy === fy) return;
    // x and y as well, so the move shows on the next frame rather than the
    // next simulation tick, which a settled layout may never run.
    Object.assign(node, { fx, fy, x: fx, y: fy });
    moved = true;
  });
  return moved;
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
