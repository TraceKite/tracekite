import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { forceCollide, forceX, forceY } from "d3-force";

import type { ServiceMapResponse } from "@/lib/types";
import { frameGraph } from "@/lib/graphCameraFit";
import { isolateColumns } from "@/lib/serviceMapIsolateBlock";
import { MAX_SERVICE_LABEL_PX } from "@/lib/serviceMapLabel";
import { SERVICE_MAP_FRAMING, serviceMapForces } from "@/lib/serviceMapLayout";
import {
  linkedIds, pinIsolates, projectServiceMap, type ServiceMapProjection,
} from "@/lib/serviceMapProjection";

interface Options {
  graphRef: RefObject<any>;
  /** False until react-force-graph has loaded; there are no forces to tune. */
  graphLoaded: boolean;
  data: ServiceMapResponse | null;
  mapEdgeTypes: string[];
  scopeRepoIds: string[];
  dimensions: { width: number; height: number };
}

export interface ServiceMapLayout {
  graphData: ServiceMapProjection;
  /** False while the layout is still being arranged. */
  layoutReady: boolean;
  onEngineStop: () => void;
}

/** Settle after this long even if onEngineStop never fires, which it does not
 * when the simulation is already cool. */
const SETTLE_FALLBACK_MS = 1400;

/**
 * The service map's projection, forces and framing.
 *
 * The canvas size is read through a ref everywhere but one place, because
 * nothing about a resize should reach the layout: projecting again hands
 * force-graph new node objects and it lays new objects out from scratch, which
 * is what every resize did while the width was an input to the projection. The
 * one place is the isolate block, whose column count really does depend on the
 * width — and it re-wraps the nodes it already has, in place.
 */
export function useServiceMapLayout({
  graphRef, graphLoaded, data, mapEdgeTypes, scopeRepoIds, dimensions,
}: Options): ServiceMapLayout {
  const [layoutReady, setLayoutReady] = useState(false);
  const dimensionsRef = useRef(dimensions);
  dimensionsRef.current = dimensions;

  const graphData = useMemo(
    () => projectServiceMap(data, mapEdgeTypes, scopeRepoIds,
                            { canvasWidthPx: dimensionsRef.current.width }),
    [data, mapEdgeTypes, scopeRepoIds],
  );

  /** What the last settle left in place, so a resize knows if it changed it. */
  const settled = useRef<{ graphData: ServiceMapProjection; columns: number } | null>(null);

  /** Parks the isolates under the graph as it now lies, then frames the whole. */
  const settle = useCallback(() => {
    const { width: canvasWidthPx, height: canvasHeightPx } = dimensionsRef.current;
    pinIsolates(graphData, { canvasWidthPx, canvasHeightPx });
    frameGraph(graphRef.current, dimensionsRef.current, SERVICE_MAP_FRAMING);
    settled.current = {
      graphData,
      columns: isolateColumns(graphData.isolated, canvasWidthPx, MAX_SERVICE_LABEL_PX),
    };
  }, [graphData, graphRef]);

  const columns = isolateColumns(graphData.isolated, dimensions.width, MAX_SERVICE_LABEL_PX);
  useEffect(() => {
    const last = settled.current;
    // A projection not yet settled is the layout's to settle, below.
    if (!last || last.graphData !== graphData || last.columns === columns) return;
    settle();
  }, [columns, graphData, settle]);

  useEffect(() => {
    setLayoutReady(false);
    return runLayout(graphRef, () => {
      applyForces(graphRef.current, graphData, dimensionsRef.current);
    }, () => {
      settle();
      setLayoutReady(true);
    });
  }, [graphData, graphLoaded, graphRef, settle]);

  const onEngineStop = useCallback(() => {
    settle();
    setLayoutReady(true);
  }, [settle]);

  return { graphData, layoutReady, onEngineStop };
}

/**
 * Tunes the forces once react-force-graph has created them — it has not on
 * the first pass, so this retries — then reheats and settles after a fallback
 * delay. Returns the cancel for the effect that started it.
 */
function runLayout(
  graphRef: RefObject<any>,
  tune: () => void,
  settled: () => void,
): () => void {
  let cancelled = false;
  let tries = 0;
  const attempt = () => {
    if (cancelled) return;
    if (!graphRef.current?.d3Force?.("charge")) {
      if (tries++ < 25) setTimeout(attempt, 80);
      return;
    }
    tune();
    graphRef.current.d3ReheatSimulation?.();
    setTimeout(() => { if (!cancelled) settled(); }, SETTLE_FALLBACK_MS);
  };
  attempt();
  return () => { cancelled = true; };
}

/* Isolates are pinned, but pinned nodes still push: they kept their charge and
 * collision radius, so the graph arranged itself around wherever they were
 * parked and had a hole where they had been once the block moved below it.
 * They take no part in the graph's physics now, only in its framing. */
function applyForces(
  graph: any,
  graphData: ServiceMapProjection,
  { width, height }: { width: number; height: number },
): void {
  const forces = serviceMapForces(graphData.nodes.length);
  const linked = linkedIds(graphData.links);
  const inGraph = (node: any) => linked.has(node.id);
  graph.d3Force("charge")
    .strength((node: any) => (inGraph(node) ? forces.chargeStrength : 0))
    .distanceMax(forces.chargeDistanceMax);
  graph.d3Force("link")?.distance(forces.linkDistance);
  graph.d3Force("center")?.strength(forces.centerStrength);
  const aspect = Math.max(width / Math.max(height, 1), 0.2);
  graph.d3Force("x", forceX(0).strength(0.05 / aspect));
  graph.d3Force("y", forceY(0).strength(0.05 * aspect));
  graph.d3Force("collide", forceCollide((node: any) =>
    (inGraph(node) ? forces.collideRadius : 0)).iterations(2));
}
