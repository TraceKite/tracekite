import { useCallback, useEffect, useRef, type RefObject } from "react";

import type { GraphNode } from "@/lib/types";
import { fitTarget } from "@/lib/graphCameraFit";
import type { ForceGraph2DMethods } from "@/hooks/useGraphControls";

interface Options {
  graphRef: RefObject<ForceGraph2DMethods | null>;
  nodes: GraphNode[];
  dimensions: { width: number; height: number };
  ready: boolean;
  /**
   * Identity of the drawn scene: scope, view mode, focus fetch and expanded
   * module. It deliberately excludes the selected node — selecting one keeps
   * the same node objects at the same coordinates, so the camera still frames
   * what the user is looking at.
   */
  sceneKey: string;
  selectedNodeId: string | null;
}

export interface Graph2DCameraFrame {
  onEngineStop: () => void;
  onUserZoom: () => void;
}

const FIT_MS = 600;
const FIT_PADDING = 70;
// Long enough for the layout to spread, short enough that a new scene does not
// sit unframed. The engine's own settle lands later and matters only when the
// canvas was still remounting at this point, which is what the retry covers.
const FIT_FALLBACK_MS = 1200;
const FIT_RETRY_MS = 200;
const FIT_RETRIES = 6;
// How far a selected node may sit from the edge before the camera pans to it.
const EDGE_MARGIN = 80;

export function useGraph2DCameraFrame({
  graphRef,
  nodes,
  dimensions,
  ready,
  sceneKey,
  selectedNodeId,
}: Options): Graph2DCameraFrame {
  const pendingRef = useRef<string | null>(null);
  const framedRef = useRef<string | null>(null);
  const centeredRef = useRef<string | null>(null);
  const hasNodes = nodes.length > 0;
  // A canvas still waiting for its first layout measures 0x0. Read at fit time
  // as well as at arming time: a fit owed from earlier must not land during a
  // moment when the canvas has no size.
  const measured = dimensions.width > 1 && dimensions.height > 1;
  const measuredRef = useRef(measured);
  measuredRef.current = measured;
  const dimensionsRef = useRef(dimensions);
  dimensionsRef.current = dimensions;

  // Returns false while the fit cannot be trusted — no graph instance, or a
  // canvas with no size yet — so the caller knows it is still owed. Fitting to
  // an unmeasured canvas divides by nothing and clamps to the minimum zoom,
  // which lands the graph as a speck.
  const fitNow = useCallback(() => {
    const scene = pendingRef.current;
    if (!scene) return true;
    const graph = graphRef.current;
    if (!graph || !measuredRef.current) return false;
    // Framed here rather than through zoomToFit, which has no upper bound and
    // scales a one-node module until it fills the screen.
    const target = fitTarget(
      graph.getGraphBbox?.(), dimensionsRef.current, FIT_PADDING);
    if (!target) return false;
    pendingRef.current = null;
    framedRef.current = scene;
    graph.centerAt(target.x, target.y, FIT_MS);
    graph.zoom(target.zoom, FIT_MS);
    return true;
  }, [graphRef]);

  useEffect(() => {
    if (!ready || !hasNodes || !measured) return;
    if (framedRef.current === sceneKey) return;
    pendingRef.current = sceneKey;
    let timer = 0;
    const attempt = (left: number) => {
      if (fitNow() || left <= 0) return;
      timer = window.setTimeout(() => attempt(left - 1), FIT_RETRY_MS);
    };
    timer = window.setTimeout(() => attempt(FIT_RETRIES), FIT_FALLBACK_MS);
    return () => window.clearTimeout(timer);
  }, [fitNow, hasNodes, measured, ready, sceneKey]);

  // Reads the wheel in the capture phase, because force-graph's own zoom
  // handler stops the event at the canvas. Zooming animates through the same
  // d3 transform we would, so the gesture is the only honest signal that the
  // reader — not us — is framing this scene.
  const onUserZoom = useCallback(() => {
    const scene = pendingRef.current;
    if (!scene) return;
    pendingRef.current = null;
    framedRef.current = scene;
  }, []);

  useEffect(() => {
    if (!selectedNodeId) {
      centeredRef.current = null;
      return;
    }
    if (!measured || centeredRef.current === selectedNodeId) return;
    const selected = nodes.find((node) => node.id === selectedNodeId) as
      (GraphNode & { x?: number; y?: number }) | undefined;
    if (selected?.x == null || selected.y == null) return;
    centeredRef.current = selectedNodeId;
    const screen = graphRef.current?.graph2ScreenCoords?.(selected.x, selected.y);
    const outside = !screen || screen.x < EDGE_MARGIN || screen.y < EDGE_MARGIN ||
      screen.x > dimensions.width - EDGE_MARGIN ||
      screen.y > dimensions.height - EDGE_MARGIN;
    // Pan only. The zoom level is the user's, including when the selection
    // arrives from search rather than from a click on the canvas.
    if (outside) graphRef.current?.centerAt(selected.x, selected.y, 450);
  }, [dimensions.height, dimensions.width, graphRef, measured, nodes, selectedNodeId]);

  return { onEngineStop: fitNow, onUserZoom };
}
