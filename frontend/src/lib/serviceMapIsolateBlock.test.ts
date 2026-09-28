import assert from "node:assert/strict";
import test from "node:test";

import { isolateBlock, isolateColumns } from "./serviceMapIsolateBlock.ts";

/** The canvas and label budget the service map actually runs with. */
const CANVAS = 750;
const BUDGET = 180;
const block = (count: number, linkDistance = 220, nodeCount = count) =>
  isolateBlock({ count, nodeCount, linkDistance,
                 canvasWidthPx: CANVAS, labelBudgetPx: BUDGET });

test("a row holds as many labels as the canvas has room for", () => {
  // 750px of canvas, 180px labels and a 20px gutter: three across.
  assert.equal(isolateColumns(10, CANVAS, BUDGET), 3);
});

test("fewer isolates than columns stay on one row", () => {
  assert.equal(isolateColumns(2, CANVAS, BUDGET), 2);
  assert.deepEqual(new Set(block(3).map((p) => p.fy)).size, 1);
});

test("the block widens against the graph it shares a canvas with", () => {
  // Sized as a flat share of the link distance, the block lost the race for
  // the fitted zoom and three of six isolates went unlabelled. It now grows
  // with the layout's extent, which goes as the square root of the node count.
  const beside16 = block(6, 220, 16);
  const beside55 = block(6, 220, 55);
  const gap = (p: { fx: number }[]) => p[1].fx - p[0].fx;

  assert.ok(gap(beside55) > gap(beside16),
            `${gap(beside55)} beside 55 nodes should beat ${gap(beside16)} beside 16`);
});

test("before the layout runs, the block starts lower as the graph grows", () => {
  // A top scaled by the link distance alone stayed put while the graph around
  // it widened, and all seven isolates of the 55-node estate sat inside it.
  const top = (nodeCount: number) => block(3, 220, nodeCount)[0].fy;

  assert.ok(top(55) > top(16), `${top(55)} beside 55 nodes against ${top(16)} beside 16`);
  assert.ok(Math.abs(top(64) / top(16) - 2) < 1e-9, "the top grows as sqrt(nodes)");
});

test("once laid out, the block starts below the graph's lowest node", () => {
  const placed = isolateBlock({
    count: 3, nodeCount: 20, linkDistance: 200, canvasWidthPx: CANVAS,
    labelBudgetPx: BUDGET, graph: { left: -200, right: 200, top: 0, bottom: 500 },
  });

  assert.ok(placed.every((p) => p.fy > 500), `rows at ${placed.map((p) => p.fy)}`);
});

test("once laid out, the block is centred under the graph, not the origin", () => {
  const placed = isolateBlock({
    count: 3, nodeCount: 20, linkDistance: 200, canvasWidthPx: CANVAS,
    labelBudgetPx: BUDGET, graph: { left: 50, right: 450, top: 0, bottom: 500 },
  });

  assert.equal(placed.reduce((sum, p) => sum + p.fx, 0) / placed.length, 250);
});

test("under a tall graph, every cell keeps its label's budget at the fitted zoom", () => {
  // Height binds here: 900 units of graph and block into a 570px-high usable
  // canvas fits at ~0.6, where a share-of-extent cell was ~120px — too narrow
  // for a 180px label, and two of six isolate names were dropped.
  const framing = { canvasHeightPx: 750, paddingPx: 90, minZoom: 0.3, maxZoom: 2.5 };
  const graph = { left: -150, right: 150, top: -300, bottom: 400 };
  const placed = isolateBlock({
    count: 6, nodeCount: 16, linkDistance: 152, canvasWidthPx: 963,
    labelBudgetPx: BUDGET, graph, framing,
  });
  const bottom = Math.max(...placed.map((p) => p.fy));
  const zoom = Math.min(2.5, (963 - 180) / 300, (750 - 180) / (bottom - graph.top));
  const pitchPx = (placed[1].fx - placed[0].fx) * zoom;

  assert.ok(pitchPx >= BUDGET + 20 - 1e-9, `cells ${pitchPx}px apart at zoom ${zoom}`);
});

test("without framing, the cells keep their share of the layout's extent", () => {
  const graph = { left: -150, right: 150, top: -300, bottom: 400 };
  const withFraming = isolateBlock({
    count: 6, nodeCount: 16, linkDistance: 152, canvasWidthPx: 963, labelBudgetPx: BUDGET,
    graph, framing: { canvasHeightPx: 750, paddingPx: 90, minZoom: 0.3, maxZoom: 2.5 },
  });
  const without = isolateBlock({
    count: 6, nodeCount: 16, linkDistance: 152, canvasWidthPx: 963, labelBudgetPx: BUDGET, graph,
  });

  assert.ok(withFraming[1].fx - withFraming[0].fx > without[1].fx - without[0].fx);
});

test("more isolates than fit across wrap onto further rows", () => {
  // Six names that wanted 900px of a 750px canvas: the case that lost four
  // of its six labels while they were all on one line.
  const placed = block(6);
  const rows = new Set(placed.map((p) => p.fy));

  assert.equal(rows.size, 2);
  assert.equal(placed.filter((p) => p.fy === placed[0].fy).length, 3);
});

test("every row is centred, so a short last row does not lean", () => {
  for (const count of [1, 2, 3, 4, 5, 6, 7, 11]) {
    const placed = block(count);
    const byRow = new Map<number, number[]>();
    for (const p of placed) byRow.set(p.fy, [...(byRow.get(p.fy) ?? []), p.fx]);
    for (const [row, xs] of byRow) {
      const sum = xs.reduce((total, x) => total + x, 0);
      assert.ok(Math.abs(sum) < 1e-9,
                `count ${count} row ${row} leans by ${sum}`);
    }
  }
});

test("the block scales with the map, like everything else in the layout", () => {
  const small = block(6, 220);
  const large = block(6, 590);

  assert.ok(large[1].fx - large[0].fx > small[1].fx - small[0].fx);
  assert.ok(large[3].fy - large[0].fy > small[3].fy - small[0].fy);
});

test("rows are pitched tighter than columns, because labels are wide", () => {
  const placed = block(6);
  const columnGap = placed[1].fx - placed[0].fx;
  const rowGap = placed[3].fy - placed[0].fy;

  assert.ok(rowGap < columnGap, `${rowGap} row against ${columnGap} column`);
});

test("a canvas too narrow for even one label still yields a column", () => {
  assert.equal(isolateColumns(5, 10, BUDGET), 1);
});

test("nothing to place is not an error", () => {
  assert.deepEqual(block(0), []);
});
