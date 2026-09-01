import { useEffect, useRef, type MutableRefObject, type RefObject } from "react";

import { projectNodesToScreen, syncBuffersToGPU } from "@/lib/graph3dBufferBuilder";
import { computeClusterCentroids, updateClusterHolo, type ClusterHoloPool } from "@/lib/graph3dClusterHolo";
import { updateDampedCamera } from "@/lib/graph3dFrameStepper";
import { findHoveredNode } from "@/lib/graph3dHover";
import type { DomHoverTooltip } from "@/lib/graph3dHoverTooltip";
import { updateDomLabels, type DomLabelPool } from "@/lib/graph3dLabelPlacer";
import {
  stepPhysicsSimulation, type Layout3DMode, type LayoutAnchors,
  type Node3DPhysicsState,
} from "@/lib/graph3dPhysics";
import type { Scene3DContext } from "@/lib/graph3dSceneInit";
import type { GraphLink } from "@/lib/types";
import type { Camera3DState } from "@/hooks/useGraph3DInteraction";
import type { ProjectionMode } from "@/hooks/useGraphProjection";

interface Options {
  containerRef: RefObject<HTMLDivElement | null>;
  threeRef: RefObject<Scene3DContext | null>;
  labelPoolRef: RefObject<DomLabelPool | null>;
  clusterPoolRef: RefObject<ClusterHoloPool | null>;
  tooltipRef: RefObject<DomHoverTooltip | null>;
  camRef: RefObject<Camera3DState>;
  physicsNodesRef: MutableRefObject<Node3DPhysicsState[]>;
  anchorsRef: MutableRefObject<LayoutAnchors>;
  alphaRef: MutableRefObject<number>;
  hoverNodeRef: MutableRefObject<string | null>;
  layoutRef: MutableRefObject<Layout3DMode>;
  flowRef: MutableRefObject<boolean>;
  labelsRef: MutableRefObject<boolean>;
  orbitRef: MutableRefObject<boolean>;
  selectedRef: MutableRefObject<string | null>;
  pathRef: MutableRefObject<string[] | null>;
  searchRef: MutableRefObject<string>;
  highlightsRef: MutableRefObject<string[]>;
  linksRef: MutableRefObject<GraphLink[]>;
  nodeIndexMapRef: MutableRefObject<Map<string, number>>;
  projectionMode: ProjectionMode;
}

export function useGraph3DRenderer(options: Options) {
  const projectionRef = useRef(options.projectionMode);
  projectionRef.current = options.projectionMode;

  useEffect(() => {
    let animationId: number;
    let lastTime = performance.now();
    let lastRenderTime = 0;
    const startTime = performance.now();

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const scene = options.threeRef.current;
      const camera = options.camRef.current;
      const element = options.containerRef.current;
      const physicsNodes = options.physicsNodesRef.current;
      if (!scene || !camera || !element || physicsNodes.length === 0) return;

      const now = performance.now();
      const active = options.alphaRef.current > 0.003 || options.flowRef.current ||
        options.orbitRef.current || camera.isDragging || camera.cursorPos.live;
      if (!active && now - lastRenderTime < 100) return;
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;
      lastRenderTime = now;

      const layout = options.layoutRef.current;
      const anchors = options.anchorsRef.current[layout] || options.anchorsRef.current.atlas;
      stepPhysicsSimulation(physicsNodes, options.linksRef.current,
        options.nodeIndexMapRef.current, anchors, options.alphaRef.current);
      options.alphaRef.current = Math.max(0.002, options.alphaRef.current * 0.988);
      syncBuffersToGPU(
        scene.nodeGeo, scene.edgeGeo, physicsNodes, options.linksRef.current,
        options.nodeIndexMapRef.current, options.selectedRef.current,
        options.hoverNodeRef.current, options.pathRef.current, [], [],
        options.searchRef.current || "", false, false, options.highlightsRef.current,
      );
      scene.flowMat.uniforms.uTime.value = (now - startTime) * 0.001;
      scene.flowMat.uniforms.uFlow.value = options.flowRef.current ? 1 : 0;
      scene.sphereRings.visible = layout === "sphere";
      updateDampedCamera(scene.camera, camera, dt, options.orbitRef.current);

      const width = element.clientWidth;
      const height = element.clientHeight;
      projectNodesToScreen(physicsNodes, scene.camera, width, height);
      const hovered = camera.cursorPos.live && !camera.isDragging
        ? findHoveredNode(physicsNodes, camera.cursorPos.x, camera.cursorPos.y)
        : null;
      options.hoverNodeRef.current = hovered?.id ?? null;
      element.style.cursor = hovered ? "pointer" : "grab";
      options.tooltipRef.current?.update(
        hovered?.node ?? null, options.linksRef.current,
        camera.cursorPos.x, camera.cursorPos.y, width, height);
      scene.renderer.render(scene.scene, scene.camera);
      if (options.labelPoolRef.current) {
        updateDomLabels(
          options.labelPoolRef.current, physicsNodes, options.linksRef.current,
          width, height, options.selectedRef.current, options.hoverNodeRef.current,
          options.pathRef.current, options.labelsRef.current,
          projectionRef.current === "overview" ? 24 : 12);
      }
      const clusters = layout === "atlas" ? computeClusterCentroids(physicsNodes) : [];
      if (options.clusterPoolRef.current) {
        updateClusterHolo(options.clusterPoolRef.current, clusters, scene.camera, width, height);
      }
    };

    animationId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animationId);
  }, []);
}
