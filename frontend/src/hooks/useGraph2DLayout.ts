import { useCallback, useEffect, useMemo, useRef, type RefObject } from "react";
import { forceCollide, forceX, forceY } from "d3-force";

import { getNodeSize } from "@/lib/graphStyle";
import { endpointId } from "@/lib/graphVisibility";
import {
  useGraphControls,
  type ForceGraph2DMethods,
} from "@/hooks/useGraphControls";
import type { GraphLink, GraphNode, ViewMode } from "@/lib/types";

interface LayoutOptions {
  graphRef: RefObject<ForceGraph2DMethods | null>;
  nodes: GraphNode[];
  links: GraphLink[];
  dimensions: { width: number; height: number };
  showLabels: boolean;
  engineReady: boolean;
  scopeKey: string;
  viewMode: ViewMode;
  selectedNodeId: string | null;
}

export function useGraph2DLayout({
  graphRef,
  nodes,
  links,
  dimensions,
  showLabels,
  engineReady,
  scopeKey,
  viewMode,
  selectedNodeId,
}: LayoutOptions): boolean {
  const physicsEnabled = useGraphControls(graphRef, nodes);
  const fittedKeyRef = useRef<string | null>(null);

  const childCount = useMemo(() => {
    const counts = new Map<string, number>();
    for (const link of links) {
      const source = endpointId(link.source);
      counts.set(source, (counts.get(source) ?? 0) + 1);
    }
    return counts;
  }, [links]);

  const linkDistance = useCallback((link: GraphLink) => {
    const base = (() => {
      switch (link.type) {
        case "CONTAINS": return 28;
        case "IMPORTS":
        case "CALLS": return 75;
        case "EXTENDS":
        case "IMPLEMENTS": return 60;
        case "EXPOSES_API": return 90;
        default: return 50;
      }
    })();
    const children = childCount.get(endpointId(link.source)) ?? 1;
    if (children <= 3) return base;
    return Math.min(Math.max(base, (children * 17) / (2 * Math.PI)), 260);
  }, [childCount]);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    const apply = () => {
      if (cancelled) return;
      const graph = graphRef.current;
      if (!graph?.d3Force) {
        if (attempts++ < 25) window.setTimeout(apply, 80);
        return;
      }
      graph.d3Force("charge")?.strength(-120)?.distanceMax(600);
      graph.d3Force("link")?.distance(linkDistance)?.strength(0.6);
      const aspect = Math.max(dimensions.width / Math.max(dimensions.height, 1), 0.2);
      const strength = 0.05;
      graph.d3Force("x", forceX(0).strength(strength / aspect));
      graph.d3Force("y", forceY(0).strength(strength * aspect));
      graph.d3Force("collide", forceCollide<any>()
        .radius((node) => {
          const radius = getNodeSize(node.type, Math.min(node.size || 5, 10)) * 0.55 + 2;
          return showLabels ? radius + 9 : radius;
        })
        .iterations(2));
      if (physicsEnabled) graph.d3ReheatSimulation?.();
    };
    apply();
    return () => { cancelled = true; };
  }, [dimensions.height, dimensions.width, engineReady, graphRef, linkDistance,
      physicsEnabled, showLabels]);

  useEffect(() => {
    if (!nodes.length || !engineReady) return;
    const fitKey = `${scopeKey}:${viewMode}`;
    if (fittedKeyRef.current === fitKey) return;
    fittedKeyRef.current = fitKey;
    const timer = window.setTimeout(() => graphRef.current?.zoomToFit(700, 70), 900);
    return () => window.clearTimeout(timer);
  }, [engineReady, graphRef, nodes.length, scopeKey, viewMode]);

  useEffect(() => {
    if (!selectedNodeId) return;
    const selected = nodes.find((node) => node.id === selectedNodeId) as
      (GraphNode & { x?: number; y?: number }) | undefined;
    if (selected?.x == null || selected.y == null) return;
    const screen = graphRef.current?.graph2ScreenCoords?.(selected.x, selected.y);
    const outside = !screen || screen.x < 80 || screen.y < 80 ||
      screen.x > dimensions.width - 80 || screen.y > dimensions.height - 80;
    if (outside) graphRef.current?.centerAt(selected.x, selected.y, 450);
  }, [dimensions.height, dimensions.width, graphRef, nodes, selectedNodeId]);

  return physicsEnabled;
}
