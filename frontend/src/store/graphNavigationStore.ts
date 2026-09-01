import { create } from "zustand";

import { synchronizeGraphContext } from "@/lib/graphNavigation";

interface GraphNavigationState {
  contextKey: string | null;
  expandedGroup: string | null;
  syncContext: (contextKey: string) => void;
  setExpandedGroup: (group: string | null, contextKey: string) => void;
  clearExpandedGroup: () => void;
  resetNavigation: () => void;
}

export const useGraphNavigationStore = create<GraphNavigationState>((set) => ({
  contextKey: null,
  expandedGroup: null,
  syncContext: (contextKey) => set((state) =>
    synchronizeGraphContext(state, contextKey)),
  setExpandedGroup: (expandedGroup, contextKey) => set({
    contextKey,
    expandedGroup,
  }),
  clearExpandedGroup: () => set({ expandedGroup: null }),
  resetNavigation: () => set({ contextKey: null, expandedGroup: null }),
}));
