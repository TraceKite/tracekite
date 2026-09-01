import type { GraphNode } from "./types.ts";
import { isModuleGroup, moduleGroupKey } from "./graphOverviewProjection.ts";

/**
 * What a click on a node means.
 *
 * Selecting and opening are different requests: selecting fills the details
 * drawer and leaves the canvas alone, opening replaces what the canvas draws.
 * One click should not do both, so opening takes the second click.
 */
export type NodeGesture =
  | { kind: "open-group"; groupKey: string }
  | { kind: "select" }
  | { kind: "select-and-open" }
  | { kind: "ignore" };

export interface ClickMemory {
  nodeId: string;
  at: number;
}

export const DOUBLE_CLICK_MS = 400;

export type OpenTarget =
  | { kind: "group"; groupKey: string }
  | { kind: "node"; nodeId: string };

/** What opening this node means: a module opens into its members. */
export function openTarget(node: GraphNode): OpenTarget {
  const groupKey = moduleGroupKey(node);
  return isModuleGroup(node) && groupKey
    ? { kind: "group", groupKey }
    : { kind: "node", nodeId: node.id };
}

/**
 * Recognises the second click of a double-click from the node and the clock.
 * force-graph raises its click callbacks from `pointerup`, whose `detail` is
 * always 0, so the browser's own click count is not available there.
 */
export function isSecondClick(
  previous: ClickMemory | null,
  nodeId: string,
  at: number,
): boolean {
  if (!previous || previous.nodeId !== nodeId) return false;
  return at - previous.at <= DOUBLE_CLICK_MS;
}

export function nodeClickGesture(
  node: GraphNode,
  secondClick: boolean,
  timeStamp: number,
  groupOpenedAt: number,
): NodeGesture {
  // Opening a module slides a member under the cursor mid-gesture. A click
  // arriving that fast is aimed at the module, not at the member.
  if (timeStamp - groupOpenedAt < DOUBLE_CLICK_MS) return { kind: "ignore" };
  if (!secondClick) return { kind: "select" };
  // One rule for every kind of node: the first click reads, the second opens.
  const target = openTarget(node);
  return target.kind === "group"
    ? { kind: "open-group", groupKey: target.groupKey }
    : { kind: "select-and-open" };
}
