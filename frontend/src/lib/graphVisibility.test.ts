import assert from "node:assert/strict";
import test from "node:test";

import {
  endpointId,
  isLinkVisible,
  isLockfileDependencyNode,
  isNodeVisible,
} from "./graphVisibility.ts";

const node = (overrides: Record<string, unknown> = {}) => ({
  id: "n1",
  type: "File",
  label: "file.ts",
  name: "file.ts",
  size: 1,
  group: "File",
  metadata: {},
  ...overrides,
}) as any;

test("hidden node types use the same exclude semantics in both dimensions", () => {
  assert.equal(isNodeVisible(node({ type: "File" }), ["File"], false), false);
  assert.equal(isNodeVisible(node({ type: "Folder" }), ["File"], false), true);
});

test("lockfile dependencies can be suppressed without hiding direct dependencies", () => {
  const lockfile = node({ type: "Dependency", path: "frontend/pnpm-lock.yaml" });
  const direct = node({ type: "Dependency", path: "frontend/package.json" });
  assert.equal(isLockfileDependencyNode(lockfile), true);
  assert.equal(isNodeVisible(lockfile, [], true), false);
  assert.equal(isNodeVisible(direct, [], true), true);
});

test("an edge is visible only when its type and both endpoints are visible", () => {
  const link = { source: { id: "a" }, target: "b", type: "CALLS" } as any;
  assert.equal(endpointId(link.source), "a");
  assert.equal(isLinkVisible(link, [], new Set(["a", "b"])), true);
  assert.equal(isLinkVisible(link, ["CALLS"], new Set(["a", "b"])), false);
  assert.equal(isLinkVisible(link, [], new Set(["a"])), false);
});
