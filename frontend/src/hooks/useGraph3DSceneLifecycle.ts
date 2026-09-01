import { useEffect, useRef } from "react";
import * as THREE from "three";
import { init3DScene, dispose3DScene, type Scene3DContext } from "@/lib/graph3dSceneInit";
import { createDomLabelPool, type DomLabelPool } from "@/lib/graph3dLabelPlacer";
import { createClusterHoloPool, type ClusterHoloPool, type ClusterInfo } from "@/lib/graph3dClusterHolo";
import { createDomHoverTooltip, type DomHoverTooltip } from "@/lib/graph3dHoverTooltip";
import type { Camera3DState } from "@/hooks/useGraph3DInteraction";

interface LifecycleProps {
  containerRef: React.RefObject<HTMLDivElement | null>;
  camRef: React.RefObject<Camera3DState>;
  onSelectNode: (nodeId: string, pathMode?: boolean) => void;
  onFocusCluster?: (cluster: ClusterInfo) => void;
}

export function useGraph3DSceneLifecycle({
  containerRef,
  camRef,
  onSelectNode,
  onFocusCluster,
}: LifecycleProps) {
  const threeRef = useRef<Scene3DContext | null>(null);
  const labelPoolRef = useRef<DomLabelPool | null>(null);
  const clusterPoolRef = useRef<ClusterHoloPool | null>(null);
  const tooltipRef = useRef<DomHoverTooltip | null>(null);
  const selectNodeRef = useRef(onSelectNode);
  const focusClusterRef = useRef(onFocusCluster);
  // DOM label listeners outlive React renders, so they must dereference the
  // current navigation context instead of capturing the first View Mode.
  selectNodeRef.current = onSelectNode;
  focusClusterRef.current = onFocusCluster;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const ctx = init3DScene(el, true);
    threeRef.current = ctx;

    const labelPool = createDomLabelPool(el, 24,
      (nodeId, pathMode) => selectNodeRef.current(nodeId, pathMode));
    labelPoolRef.current = labelPool;

    const clusterPool = createClusterHoloPool(el, (c) => {
      if (focusClusterRef.current) {
        focusClusterRef.current(c);
        return;
      }
      if (camRef.current) {
        camRef.current.targetLook.set(c.x, c.y, c.z);
        camRef.current.tDist = camRef.current.baseDist * 0.75;
      }
    });
    clusterPoolRef.current = clusterPool;

    const tooltip = createDomHoverTooltip(el);
    tooltipRef.current = tooltip;

    const handleResize = () => {
      if (!el || !threeRef.current) return;
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w === 0 || h === 0) return;
      threeRef.current.camera.aspect = w / h;
      threeRef.current.camera.updateProjectionMatrix();
      threeRef.current.renderer.setSize(w, h);
      const uPx = h / (2 * Math.tan((threeRef.current.camera.fov * Math.PI) / 360));
      threeRef.current.haloMat.uniforms.uPx.value = uPx;
      threeRef.current.beadMat.uniforms.uPx.value = uPx;
    };

    let ro: ResizeObserver | null = null;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(handleResize);
      ro.observe(el);
    } else {
      window.addEventListener("resize", handleResize);
    }

    return () => {
      if (ro) ro.disconnect();
      else window.removeEventListener("resize", handleResize);
      labelPool.destroy();
      clusterPool.destroy();
      tooltip.destroy();
      dispose3DScene(ctx, el);
      threeRef.current = null;
      labelPoolRef.current = null;
      clusterPoolRef.current = null;
      tooltipRef.current = null;
    };
  }, []);

  return { threeRef, labelPoolRef, clusterPoolRef, tooltipRef };
}
