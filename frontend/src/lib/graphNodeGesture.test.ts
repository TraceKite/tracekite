import assert from "node:assert/strict";
import test from "node:test";

import {
  DOUBLE_CLICK_MS, isSecondClick, nodeClickGesture, openTarget,
} from "./graphNodeGesture.ts";
import type { GraphNode } from "./types.ts";

const node = (metadata: Record<string, unknown> = {}) => ({
  id: "repo:File:abc", type: metadata.aggregate ? "ModuleGroup" : "File",
  label: "app.py", name: "app.py", size: 6, group: "repo/backend", metadata,
} as unknown as GraphNode);

const file = node();
const group = node({ aggregate: true, group_key: "repo/backend" });

test("one click reads a node, a second one opens it", () => {
  assert.deepEqual(nodeClickGesture(file, false, 1000, 0), { kind: "select" });
  assert.deepEqual(nodeClickGesture(file, true, 1000, 0), { kind: "select-and-open" });
});

test("a module follows the same rule: read it, then open it", () => {
  assert.deepEqual(nodeClickGesture(group, false, 1000, 0), { kind: "select" });
  assert.deepEqual(nodeClickGesture(group, true, 1000, 0),
    { kind: "open-group", groupKey: "repo/backend" });
});

test("the click that lands on a member a module just revealed is dropped", () => {
  assert.deepEqual(nodeClickGesture(file, true, 1000, 1000 - DOUBLE_CLICK_MS + 1),
    { kind: "ignore" });
  // Once the gesture is over, that member is clickable like any other.
  assert.deepEqual(nodeClickGesture(file, false, 1000, 1000 - DOUBLE_CLICK_MS),
    { kind: "select" });
});

test("a second click counts only on the same node, and only in time", () => {
  assert.equal(isSecondClick(null, "a", 1000), false);
  assert.equal(isSecondClick({ nodeId: "a", at: 900 }, "a", 1000), true);
  assert.equal(isSecondClick({ nodeId: "b", at: 900 }, "a", 1000), false);
  assert.equal(
    isSecondClick({ nodeId: "a", at: 1000 - DOUBLE_CLICK_MS - 1 }, "a", 1000), false);
});

test("opening a module means its members, opening anything else its neighbors", () => {
  assert.deepEqual(openTarget(group), { kind: "group", groupKey: "repo/backend" });
  assert.deepEqual(openTarget(file), { kind: "node", nodeId: "repo:File:abc" });
});
