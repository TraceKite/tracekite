import { create } from "zustand";

import { synchronizeGraphContext } from "@/lib/graphNavigation";

interface GraphNavigationState {
  contextKey: string | null;
  expandedGroup: string | null;
  expandedNodeId: string | null;
  syncContext: (contextKey: string) => void;
  setExpandedGroup: (group: string | null, contextKey: string) => void;
  setExpandedNode: (nodeId: string | null, contextKey: string) => void;
  clearExpandedGroup: () => void;
  clearExpandedNode: () => void;
  resetNavigation: () => void;
}

export const useGraphNavigationStore = create<GraphNavigationState>((set) => ({
  contextKey: null,
  expandedGroup: null,
  expandedNodeId: null,
  syncContext: (contextKey) => set((state) =>
    synchronizeGraphContext(state, contextKey)),
  // Opening a module starts a fresh level, so the node opened inside the
  // previous one does not follow the reader into it.
  setExpandedGroup: (expandedGroup, contextKey) => set({
    contextKey,
    expandedGroup,
    expandedNodeId: null,
  }),
  setExpandedNode: (expandedNodeId, contextKey) => set({
    contextKey,
    expandedNodeId,
  }),
  clearExpandedGroup: () => set({ expandedGroup: null, expandedNodeId: null }),
  clearExpandedNode: () => set({ expandedNodeId: null }),
  resetNavigation: () => set({
    contextKey: null,
    expandedGroup: null,
    expandedNodeId: null,
  }),
}));
