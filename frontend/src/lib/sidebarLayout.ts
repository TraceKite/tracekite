/**
 * When the left panel gives way to the canvas, and who gets the last word.
 *
 * The rule is width, not mood: the panel collapses when the columns the layout
 * has to place no longer leave a canvas worth drawing on. Opening a details
 * drawer raises that bar rather than collapsing the panel outright, so a wide
 * screen keeps everything it has room for.
 */

// Pixels, not Tailwind's nominal names: this app sets a 14px root, so its
// rem-based widths land at 87.5% of what the class names suggest — w-72 is
// 252px on screen, not 288.
/** Expanded panel, widest of the three views (w-80 on Trace). */
const PANEL_WIDTH = 280;
/** Node and edge details drawers, both w-80. */
const DRAWER_WIDTH = 280;
/** Below this the graph is too cramped to read, and the panel is what gives. */
const MIN_CANVAS_WIDTH = 820;

export interface SidebarOverride {
  collapsed: boolean;
  /**
   * The layout pressure the reader answered. Their choice decides that layout
   * and no other, so a panel closed by hand on a roomy screen stays closed
   * across a drawer opening, while the automatic rule still owns the layouts
   * they have not spoken about.
   */
  pressure: boolean;
}

export function sidebarPressure(viewportWidth: number, drawerOpen: boolean): boolean {
  const needed = PANEL_WIDTH + MIN_CANVAS_WIDTH + (drawerOpen ? DRAWER_WIDTH : 0);
  return viewportWidth < needed;
}

export function sidebarCollapsed(
  pressure: boolean,
  override: SidebarOverride | null,
): boolean {
  if (override && override.pressure === pressure) return override.collapsed;
  return pressure;
}
