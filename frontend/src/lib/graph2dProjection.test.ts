import assert from "node:assert/strict";
import test from "node:test";

import { buildLabelBudget, computeFocusContext } from "./graph2dProjection.ts";

const nodes = Array.from({ length: 150 }, (_, index) => ({
  id: `n${index}`,
  type: index === 0 ? "Repo" : "File",
  label: `node-${index}`,
  name: `node-${index}`,
  size: index === 0 ? 20 : 1,
  group: "File",
  metadata: {},
})) as any[];
const links = nodes.slice(1).map((node) => ({
  source: "n0",
  target: node.id,
  type: "CONTAINS",
})) as any[];

test("label budgets are deterministic and bounded", () => {
  const first = buildLabelBudget(nodes, links, null);
  const second = buildLabelBudget(nodes, links, null);
  assert.deepEqual([...first.overview], [...second.overview]);
  assert.ok(first.overview.size <= 24);
  assert.ok(first.medium.size <= 48);
  assert.ok(first.detail.size <= 96);
  assert.equal(first.overview.has("n0"), true);
});

test("focus context contains exact incident links and nodes", () => {
  const focus = computeFocusContext(links, "n1");
  assert.deepEqual([...focus.nodeIds].sort(), ["n0", "n1"]);
  assert.equal(focus.linkIds.size, 1);
});
