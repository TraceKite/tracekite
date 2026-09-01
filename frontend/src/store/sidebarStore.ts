import { create } from "zustand";

import type { SidebarOverride } from "@/lib/sidebarLayout";

interface SidebarState {
  /** null while the automatic rule is in charge. */
  override: SidebarOverride | null;
  setOverride: (override: SidebarOverride | null) => void;
}

// Separate from the graph store on purpose: the panel follows the reader
// across Repo, Service Map and Trace, none of which share graph state.
export const useSidebarStore = create<SidebarState>((set) => ({
  override: null,
  setOverride: (override) => set({ override }),
}));
