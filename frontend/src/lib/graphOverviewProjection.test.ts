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

test("outgoing impact from b reaches c only and excludes unreachable a", () => {
  const impact = buildBoundedImpact(nodes, links, "b", 2);
  assert.deepEqual(impact.nodes.map((item) => item.id), ["b", "c"]);
  assert.deepEqual(impact.links.map((item) => item.id), ["cross"]);
  assert.equal(impact.totalNodeCount, 2);
});

test("incoming impact from b reaches a only and excludes unreachable c", () => {
  const impact = buildBoundedImpact(nodes, links, "b", 2, 2, "incoming");
  assert.deepEqual(impact.nodes.map((item) => item.id), ["b", "a"]);
  assert.deepEqual(impact.links.map((item) => item.id), ["internal"]);
  assert.equal(impact.totalNodeCount, 2);
});

test("two-hop outgoing from A excludes third-hop D and disconnected Z", () => {
  // A → B → C → D, plus disconnected Z
  const chain = [
    { id: "a", path: "x/a", type: "File", label: "a", name: "a", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "b", path: "x/b", type: "File", label: "b", name: "b", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "c", path: "x/c", type: "File", label: "c", name: "c", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "d", path: "x/d", type: "File", label: "d", name: "d", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "z", path: "x/z", type: "File", label: "z", name: "z", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
  ] as any[];
  const chainLinks = [
    { id: "l1", source: "a", target: "b", type: "CALLS", confidence: 0.9 },
    { id: "l2", source: "b", target: "c", type: "CALLS", confidence: 0.9 },
    { id: "l3", source: "c", target: "d", type: "CALLS", confidence: 0.9 },
  ] as any[];
  const impact = buildBoundedImpact(chain, chainLinks, "a", 80, 2, "outgoing");
  const ids = impact.nodes.map((n) => n.id).sort();
  assert.deepEqual(ids, ["a", "b", "c"]);
  assert.ok(!ids.includes("d"), "third-hop D must be excluded");
  assert.ok(!ids.includes("z"), "disconnected Z must be excluded");
  assert.equal(impact.totalNodeCount, 3);
});

test("incoming impact from C identifies two-hop callers A and B", () => {
  const chain = [
    { id: "a", path: "x/a", type: "File", label: "a", name: "a", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "b", path: "x/b", type: "File", label: "b", name: "b", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "c", path: "x/c", type: "File", label: "c", name: "c", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "d", path: "x/d", type: "File", label: "d", name: "d", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
  ] as any[];
  const chainLinks = [
    { id: "l1", source: "a", target: "b", type: "CALLS", confidence: 0.9 },
    { id: "l2", source: "b", target: "c", type: "CALLS", confidence: 0.9 },
    { id: "l3", source: "c", target: "d", type: "CALLS", confidence: 0.9 },
  ] as any[];
  const impact = buildBoundedImpact(chain, chainLinks, "c", 80, 2, "incoming");
  const ids = impact.nodes.map((n) => n.id).sort();
  assert.deepEqual(ids, ["a", "b", "c"]);
  assert.ok(!ids.includes("d"), "outgoing D must be excluded from incoming impact");
  assert.equal(impact.totalNodeCount, 3);
});

test("cycles do not trap the BFS or duplicate nodes", () => {
  const cyclic = [
    { id: "a", path: "x/a", type: "File", label: "a", name: "a", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "b", path: "x/b", type: "File", label: "b", name: "b", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "c", path: "x/c", type: "File", label: "c", name: "c", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
  ] as any[];
  const cyclicLinks = [
    { id: "l1", source: "a", target: "b", type: "CALLS", confidence: 0.9 },
    { id: "l2", source: "b", target: "c", type: "CALLS", confidence: 0.9 },
    { id: "l3", source: "c", target: "a", type: "CALLS", confidence: 0.9 },
  ] as any[];
  const impact = buildBoundedImpact(cyclic, cyclicLinks, "a", 80, 2, "outgoing");
  const ids = impact.nodes.map((n) => n.id).sort();
  assert.deepEqual(ids, ["a", "b", "c"]);
  assert.equal(impact.nodes.length, 3);
});

test("budget truncation after reachability reports the reachable total", () => {
  const chain = [
    { id: "a", path: "x/a", type: "File", label: "a", name: "a", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "b", path: "x/b", type: "File", label: "b", name: "b", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
    { id: "c", path: "x/c", type: "File", label: "c", name: "c", size: 1,
      group: "File", metadata: {}, repo_id: "r" },
  ] as any[];
  const chainLinks = [
    { id: "l1", source: "a", target: "b", type: "CALLS", confidence: 0.9 },
    { id: "l2", source: "a", target: "c", type: "CALLS", confidence: 0.9 },
  ] as any[];
  const impact = buildBoundedImpact(chain, chainLinks, "a", 2, 2, "outgoing");
  assert.equal(impact.nodes.length, 2);
  assert.ok(impact.nodes.some((n) => n.id === "a"), "focus must be retained");
  assert.equal(impact.totalNodeCount, 3);
});

test("every broad dataset enters through groups while impact stays exact", () => {
  for (const mode of ["overview", "architecture", "code", "api", "dependencies"] as const) {
    assert.equal(usesGroupedEntry(mode), true);
  }
  assert.equal(usesGroupedEntry("impact"), false);
});

test("multi-repo layout spaces repos far enough to avoid overlap", () => {
  // Two repos, each with 1 root + 10 satellites = 11 groups
  const mkNode = (id: string, repoId: string, module: string, type = "File") => ({
    id, path: `${module}/file.ts`, type, label: id, name: id, size: 5,
    group: type, metadata: {}, repo_id: repoId, module,
  }) as any;
  const repoA = "owner_repoA";
  const repoB = "owner_repoB";
  const allNodes: any[] = [];
  for (let i = 0; i < 10; i++) {
    allNodes.push(mkNode(`a_mod${i}`, repoA, `mod${i}`));
    allNodes.push(mkNode(`b_mod${i}`, repoB, `mod${i}`));
  }
  allNodes.push(mkNode("a_repo", repoA, "Repo", "Repo"));
  allNodes.push(mkNode("b_repo", repoB, "Repo", "Repo"));

  const crossLinks = [
    { id: "x1", source: "a_mod0", target: "b_mod0", type: "CALLS", confidence: 0.9 },
  ] as any[];

  const overview = buildModuleOverview(allNodes, crossLinks);
  assert.equal(overview.nodes.length, 22);

  const repoANodes = overview.nodes.filter(n =>
    (n.metadata.group_key ?? "").startsWith("owner/repoA"));
  const repoBNodes = overview.nodes.filter(n =>
    (n.metadata.group_key ?? "").startsWith("owner/repoB"));

  let minCrossDistance = Infinity;
  for (const a of repoANodes) {
    for (const b of repoBNodes) {
      const dx = (a.x ?? 0) - (b.x ?? 0);
      const dy = (a.y ?? 0) - (b.y ?? 0);
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < minCrossDistance) minCrossDistance = dist;
    }
  }
  assert.ok(minCrossDistance >= 300,
    `minimum cross-repo distance ${minCrossDistance} should be >= 300`);
});

test("multi-repo layout staggers satellite angles to reduce overlap", () => {
  const mkNode = (id: string, repoId: string, module: string, type = "File") => ({
    id, path: `${module}/f.ts`, type, label: id, name: id, size: 3,
    group: type, metadata: {}, repo_id: repoId, module,
  }) as any;
  const allNodes: any[] = [];
  for (let i = 0; i < 6; i++) {
    allNodes.push(mkNode(`a_m${i}`, "owner_repoA", `m${i}`));
    allNodes.push(mkNode(`b_m${i}`, "owner_repoB", `m${i}`));
  }
  allNodes.push(mkNode("a_repo", "owner_repoA", "Repo", "Repo"));
  allNodes.push(mkNode("b_repo", "owner_repoB", "Repo", "Repo"));

  const overview = buildModuleOverview(allNodes, []);

  const repoASatellites = overview.nodes.filter(n =>
    (n.metadata.group_key ?? "").startsWith("owner/repoA") &&
    !(n.metadata.group_key ?? "").endsWith("/Repo"));
  const repoBSatellites = overview.nodes.filter(n =>
    (n.metadata.group_key ?? "").startsWith("owner/repoB") &&
    !(n.metadata.group_key ?? "").endsWith("/Repo"));
  const repoACenter = overview.nodes.find(n =>
    (n.metadata.group_key ?? "") === "owner/repoA/Repo");
  const repoBCenter = overview.nodes.find(n =>
    (n.metadata.group_key ?? "") === "owner/repoB/Repo");

  assert.ok(repoACenter && repoBCenter, "repo root nodes must exist");

  const angleOf = (node: any, center: any) =>
    Math.atan2((node.y ?? 0) - (center.y ?? 0), (node.x ?? 0) - (center.x ?? 0));
  const aAngles = repoASatellites.map(n => angleOf(n, repoACenter)).sort();
  const bAngles = repoBSatellites.map(n => angleOf(n, repoBCenter)).sort();
  const angleDiff = Math.abs(aAngles[0] - bAngles[0]);
  assert.ok(angleDiff > 0.01,
    `satellite angle offset ${angleDiff} should be non-zero`);
});

test("single-repo layout still works with updated scaling", () => {
  const overview = buildModuleOverview(nodes, links);
  assert.equal(overview.nodes.length, 2);
  assert.equal(overview.links.length, 1);
  assert.equal(overview.links[0].member_count, 1);
  assert.equal(overview.nodes.every((item) => Number.isFinite(item.fx)), true);
  const frontend = overview.nodes.find(
    (item) => item.metadata.group_key === "acme/repo/frontend");
  assert.equal(frontend?.metadata.internal_edge_count, 1);
});
