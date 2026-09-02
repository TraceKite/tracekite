import { useCallback, useEffect, useState, type RefObject } from "react";
import { useGraphStore } from "@/store/graphStore";

export interface ForceGraph2DMethods {
  zoomToFit: (ms?: number, padding?: number) => void;
  centerAt: (x?: number, y?: number, ms?: number) => void;
  zoom: (k?: number, ms?: number) => void;
  pauseAnimation: () => void;
  resumeAnimation: () => void;
  d3Force(name: string): any;
  d3Force(name: string, force: any | null): ForceGraph2DMethods;
  d3ReheatSimulation: () => void;
  graph2ScreenCoords?: (x: number, y: number) => { x: number; y: number };
  getGraphBbox?: () => { x: [number, number]; y: [number, number] } | null;
}

function rotateNode(node: any) {
  if (node.x == null || node.y == null) return;
  const oldX = node.x;
  const oldY = node.y;
  node.x = -oldY;
  node.y = oldX;
  if (node.fx != null || node.fy != null) {
    const oldFx = node.fx ?? oldX;
    node.fx = -(node.fy ?? oldY);
    node.fy = oldFx;
  }
  node.vx = 0;
  node.vy = 0;
}

export function useGraphControls(
  graphRef: RefObject<ForceGraph2DMethods | null>,
  nodes: any[],
): boolean {
  const setCallbacks = useGraphStore(
    (state) => state.setGraphControlCallbacks);
  const [physicsEnabled, setPhysicsEnabled] = useState(true);

  const resetCamera = useCallback(() => {
    graphRef.current?.centerAt(0, 0, 800);
    graphRef.current?.zoom(1, 800);
  }, [graphRef]);

  const fitGraph = useCallback(
    () => graphRef.current?.zoomToFit(800, 90), [graphRef]);

  const togglePhysics = useCallback(() => {
    setPhysicsEnabled((enabled) => {
      if (!enabled) graphRef.current?.d3ReheatSimulation();
      return !enabled;
    });
  }, [graphRef]);

  const rotateGraph = useCallback(() => {
    nodes.forEach(rotateNode);
    graphRef.current?.d3ReheatSimulation();
  }, [graphRef, nodes]);

  useEffect(() => {
    setCallbacks({
      resetCamera,
      fitGraph,
      togglePhysics,
      rotateGraph,
      physicsEnabled,
    });
  }, [fitGraph, physicsEnabled, resetCamera, rotateGraph, setCallbacks,
      togglePhysics]);

  return physicsEnabled;
}
