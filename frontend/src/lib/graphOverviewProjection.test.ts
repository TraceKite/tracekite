import assert from "node:assert/strict";
import test from "node:test";

import {
  buildGroupDetail,
  buildModuleOverview,
  buildOneHopNeighborhood,
  buildBoundedImpact,
  usesGroupedEntry,
} from "./graphOverviewProjection.ts";

const node = (id: string, path: string) => ({
  id, path, type: "File", label: id, name: id, size: 1,
  group: "File", metadata: {}, repo_id: "acme_repo",
}) as any;
const nodes = [
  node("a", "frontend/a.ts"),
  node("b", "frontend/b.ts"),
  node("c", "backend/c.ts"),
];
const links = [
  { id: "internal", source: "a", target: "b", type: "IMPORTS", confidence: 0.9 },
  { id: "cross", source: "b", target: "c", type: "CALLS", confidence: 0.8 },
] as any[];

test("module overview rolls up only exact cross-group relationships", () => {
  const overview = buildModuleOverview(nodes, links);
  assert.equal(overview.nodes.length, 2);
  assert.equal(overview.links.length, 1);
  assert.equal(overview.links[0].member_count, 1);
  assert.equal(overview.links[0].confidence, 0.8);
  assert.equal(overview.nodes.every((item) => Number.isFinite(item.fx)), true);
  const frontend = overview.nodes.find(
    (item) => item.metadata.group_key === "acme/repo/frontend");
  assert.equal(frontend?.metadata.internal_edge_count, 1);
});

test("group detail contains exact members and internal edges", () => {
  const detail = buildGroupDetail(nodes, links, "acme/repo/frontend");
  assert.deepEqual(detail.nodes.map((item) => item.id).sort(), ["a", "b"]);
  assert.deepEqual(detail.links.map((item) => item.id), ["internal"]);
});

test("large group detail is deterministically bounded and reports its full size", () => {
  const detail = buildGroupDetail(nodes, links, "acme/repo/frontend", 1);
  assert.deepEqual(detail.nodes.map((item) => item.id), ["a"]);
  assert.equal(detail.links.length, 0);
  assert.equal(detail.totalNodeCount, 2);
});

test("one-hop projection preserves only incident asserted edges", () => {
  const focus = buildOneHopNeighborhood(nodes, links, "b");
  assert.equal(focus.nodes.length, 3);
  assert.deepEqual(focus.links.map((item) => item.id).sort(), ["cross", "internal"]);
});

test("high-degree focus keeps the subject and reports omitted exact neighbors", () => {
  const focus = buildOneHopNeighborhood(nodes, links, "b", 2);
  assert.equal(focus.nodes.some((item) => item.id === "b"), true);
  assert.equal(focus.nodes.length, 2);
  assert.equal(focus.links.length, 1);
  assert.equal(focus.totalNodeCount, 3);
});

test("bounded impact keeps the subject and only edges between retained nodes", () => {
  const impact = buildBoundedImpact(nodes, links, "b", 2);
  assert.deepEqual(impact.nodes.map((item) => item.id), ["b", "a"]);
  assert.deepEqual(impact.links.map((item) => item.id), ["internal"]);
  assert.equal(impact.totalNodeCount, 3);
});

test("every broad dataset enters through groups while impact stays exact", () => {
  for (const mode of ["overview", "architecture", "code", "api", "dependencies"] as const) {
    assert.equal(usesGroupedEntry(mode), true);
  }
  assert.equal(usesGroupedEntry("impact"), false);
});
