import { useRef, useState, useCallback } from "react";
import * as THREE from "three";
import type { GraphNode, GraphLink } from "@/lib/types";
import { findDirectedPath } from "@/lib/graph3dPath";
import type { Node3DPhysicsState } from "@/lib/graph3dPhysics";

export interface Camera3DState {
  theta: number;
  phi: number;
  dist: number;
  tTheta: number;
  tPhi: number;
  tDist: number;
  baseDist: number;
  targetLook: THREE.Vector3;
  currLook: THREE.Vector3;
  isDragging: boolean;
  prevMouse: { x: number; y: number };
  totalDrag: number;
  cursorPos: { x: number; y: number; live: boolean };
}

export function useGraph3DInteraction(
  nodes: GraphNode[],
  links: GraphLink[],
  selectedNode: GraphNode | null,
  setSelectedNode: (n: GraphNode | null) => void,
  setActivePath3d: (p: string[] | null) => void,
  setHudMode3d: (m: "OVERVIEW" | "FOCUS" | "PATH") => void,
  onNodeActivate?: (node: GraphNode) => boolean,
) {
  const [zoomLevel, setZoomLevel] = useState(1.0);

  const camRef = useRef<Camera3DState>({
    theta: 0.7,
    phi: 1.18,
    dist: 160,
    tTheta: 0.7,
    tPhi: 1.18,
    tDist: 160,
    baseDist: 160,
    targetLook: new THREE.Vector3(0, 0, 0),
    currLook: new THREE.Vector3(0, 0, 0),
    isDragging: false,
    prevMouse: { x: 0, y: 0 },
    totalDrag: 0,
    cursorPos: { x: -1, y: -1, live: false },
  });

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    const c = camRef.current;
    (e.currentTarget as HTMLElement).focus({ preventScroll: true });
    c.isDragging = true;
    c.totalDrag = 0;
    c.prevMouse = { x: e.clientX, y: e.clientY };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent, container: HTMLElement | null) => {
    const c = camRef.current;
    if (container) {
      const rect = container.getBoundingClientRect();
      c.cursorPos.x = e.clientX - rect.left;
      c.cursorPos.y = e.clientY - rect.top;
      c.cursorPos.live = true;
    }

    if (!c.isDragging) return;
    const dx = e.clientX - c.prevMouse.x;
    const dy = e.clientY - c.prevMouse.y;
    c.totalDrag += Math.abs(dx) + Math.abs(dy);
    c.prevMouse = { x: e.clientX, y: e.clientY };
    c.tTheta -= dx * 0.0045;
    c.tPhi = Math.max(0.12, Math.min(Math.PI - 0.12, c.tPhi - dy * 0.0045));
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    camRef.current.isDragging = false;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
  }, []);

  const onPointerLeave = useCallback(() => {
    camRef.current.cursorPos.live = false;
  }, []);

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const c = camRef.current;
    const factor = 1 + Math.sign(e.deltaY) * 0.08;
    c.tDist = Math.max(c.baseDist * 0.28, Math.min(c.baseDist * 2.8, c.tDist * factor));
    setZoomLevel(c.baseDist / c.tDist);
  }, []);

  const onZoom = useCallback((factor: number) => {
    const c = camRef.current;
    c.tDist = Math.max(c.baseDist * 0.28, Math.min(c.baseDist * 2.8, c.tDist * factor));
    setZoomLevel(c.baseDist / c.tDist);
  }, []);

  const onResetZoom = useCallback(() => {
    const c = camRef.current;
    c.tDist = c.baseDist;
    setZoomLevel(1.0);
  }, []);

  const onResetView = useCallback(() => {
    const c = camRef.current;
    c.tTheta = 0.7;
    c.tPhi = 1.18;
    c.tDist = c.baseDist;
    c.targetLook.set(0, 0, 0);
    setZoomLevel(1.0);
  }, []);

  const onClearFocus = useCallback(() => {
    const c = camRef.current;
    c.targetLook.set(0, 0, 0);
    setSelectedNode(null);
    setActivePath3d(null);
    setHudMode3d("OVERVIEW");
  }, [setSelectedNode, setActivePath3d, setHudMode3d]);

  const flyToNode = useCallback((node: Node3DPhysicsState) => {
    const c = camRef.current;
    c.targetLook.set(node.x, node.y, node.z);
    c.tDist = Math.min(c.tDist, c.baseDist * 0.72);
    setZoomLevel(c.baseDist / c.tDist);
  }, []);

  const activateNode = useCallback((clicked: Node3DPhysicsState, pathMode = false) => {
    const clickedNode = clicked.node;
    if (onNodeActivate?.(clickedNode)) return;
    if (pathMode && selectedNode && selectedNode.id !== clickedNode.id) {
      const path = findDirectedPath(selectedNode.id, clickedNode.id, links);
      if (path) {
        setActivePath3d(path);
        setHudMode3d("PATH");
        return;
      }
    }
    setSelectedNode(clickedNode);
    setHudMode3d("FOCUS");
    flyToNode(clicked);
  }, [flyToNode, links, onNodeActivate, selectedNode, setActivePath3d,
      setHudMode3d, setSelectedNode]);

  const onClick = useCallback(
    (e: React.MouseEvent, pNodes: Node3DPhysicsState[]) => {
      const c = camRef.current;
      if (c.totalDrag > 6) return;

      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const gx = e.clientX - rect.left;
      const gy = e.clientY - rect.top;

      let clicked: Node3DPhysicsState | null = null;
      for (const pn of pNodes) {
        if (!pn.vis || pn.sz > 1.0) continue;
        const dx = pn.sx - gx;
        const dy = pn.sy - gy;
        const hitRadius = Math.max(16, pn.sr + 14);
        if (dx * dx + dy * dy <= hitRadius * hitRadius) {
          if (!clicked || pn.sz < clicked.sz) {
            clicked = pn;
          }
        }
      }

      if (clicked) {
        activateNode(clicked, e.shiftKey);
        return;
      }

      if (!e.shiftKey) {
        setSelectedNode(null);
        setActivePath3d(null);
        setHudMode3d("OVERVIEW");
        c.targetLook.set(0, 0, 0);
      }
    },
    [activateNode, setActivePath3d, setHudMode3d, setSelectedNode]
  );

  return {
    camRef,
    zoomLevel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerLeave,
    onWheel,
    onZoom,
    onResetZoom,
    onResetView,
    onClearFocus,
    onClick,
    flyToNode,
    activateNode,
  };
}
