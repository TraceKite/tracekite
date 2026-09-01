import { useCallback, useEffect, useState } from "react";

import { useGraphStore } from "@/store/graphStore";
import { useSidebarStore } from "@/store/sidebarStore";
import { sidebarCollapsed, sidebarPressure } from "@/lib/sidebarLayout";

interface CollapsibleSidebar {
  collapsed: boolean;
  toggle: () => void;
  /** True while the width, not the reader, is deciding. */
  automatic: boolean;
}

export function useCollapsibleSidebar(): CollapsibleSidebar {
  const { selectedNode, selectedEdge, isFullscreen } = useGraphStore();
  const { override, setOverride } = useSidebarStore();
  const [viewportWidth, setViewportWidth] = useState(
    () => (typeof window === "undefined" ? 1440 : window.innerWidth));

  useEffect(() => {
    const measure = () => setViewportWidth(window.innerWidth);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  // App.tsx renders a drawer for either selection, and neither in fullscreen.
  const drawerOpen = !isFullscreen && Boolean(selectedNode || selectedEdge);
  const pressure = sidebarPressure(viewportWidth, drawerOpen);
  const collapsed = sidebarCollapsed(pressure, override);
  const toggle = useCallback(
    () => setOverride({ collapsed: !collapsed, pressure }),
    [collapsed, pressure, setOverride]);

  return {
    collapsed,
    toggle,
    automatic: !override || override.pressure !== pressure,
  };
}
