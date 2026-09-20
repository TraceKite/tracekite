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

test("one row still starts where the block always started", () => {
  assert.deepEqual(block(3).map((p) => p.fy), [180, 180, 180]);
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
