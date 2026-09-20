import assert from "node:assert/strict";
import test from "node:test";

import { chooseServiceLabels } from "./serviceMapLabelPlacer.ts";
import type { LabelCandidate } from "./serviceMapLabelPlacer.ts";

/** A 100x20 box at (x, y), so overlaps are easy to arrange on purpose. */
function box(id: string, x: number, y: number,
             extra: Partial<LabelCandidate> = {}): LabelCandidate {
  return { id, x0: x, y0: y, x1: x + 100, y1: y + 20, priority: 0, ...extra };
}

test("labels that do not collide are all drawn", () => {
  const chosen = chooseServiceLabels([
    box("a", 0, 0), box("b", 200, 0), box("c", 400, 0),
  ]);

  assert.deepEqual([...chosen].sort(), ["a", "b", "c"]);
});

test("the higher priority keeps the box it contests", () => {
  const chosen = chooseServiceLabels([
    box("loser", 0, 0, { priority: 1 }),
    box("winner", 10, 0, { priority: 9 }),
  ]);

  assert.deepEqual([...chosen], ["winner"]);
});

test("a dropped label frees nothing it never occupied", () => {
  // The loser must not reserve space and push out a third that would fit.
  const chosen = chooseServiceLabels([
    box("winner", 0, 0, { priority: 9 }),
    box("loser", 10, 0, { priority: 1 }),
    box("clear", 150, 0, { priority: 0 }),
  ]);

  assert.deepEqual([...chosen].sort(), ["clear", "winner"]);
});

test("a pinned label outranks every priority, and displaces what it covers", () => {
  const chosen = chooseServiceLabels([
    box("other", 0, 0, { priority: 9 }),
    box("focused", 10, 0, { priority: 0, pinned: true }),
  ]);

  // The reader asked for this node by name, so it is drawn regardless. The
  // label it lands on yields rather than being printed through it.
  assert.deepEqual([...chosen], ["focused"]);
});

test("two pinned labels are both drawn even against each other", () => {
  const chosen = chooseServiceLabels([
    box("a", 0, 0, { pinned: true, priority: 0 }),
    box("b", 10, 0, { pinned: true, priority: 0 }),
  ]);

  assert.deepEqual([...chosen].sort(), ["a", "b"]);
});

test("equal priorities resolve by id, so the map does not flicker", () => {
  const first = chooseServiceLabels([box("zzz", 0, 0), box("aaa", 10, 0)]);
  const again = chooseServiceLabels([box("aaa", 10, 0), box("zzz", 0, 0)]);

  assert.deepEqual([...first], ["aaa"]);
  assert.deepEqual([...first], [...again]);
});

test("boxes that only share a row still both draw", () => {
  const chosen = chooseServiceLabels([box("a", 0, 0), box("b", 100, 0)]);

  // Touching edges is not overlapping.
  assert.deepEqual([...chosen].sort(), ["a", "b"]);
});

test("a collision across a row band is still a collision", () => {
  // Bands are an index, not a rule: boxes must not slip past each other by
  // straddling the boundary between two of them.
  const chosen = chooseServiceLabels([
    box("a", 0, 15, { priority: 9 }),
    box("b", 0, 25, { priority: 1 }),
  ]);

  assert.deepEqual([...chosen], ["a"]);
});

test("nothing to place is not an error", () => {
  assert.equal(chooseServiceLabels([]).size, 0);
});
