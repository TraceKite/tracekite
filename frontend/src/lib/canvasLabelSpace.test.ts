import assert from "node:assert/strict";
import test from "node:test";

import { LabelSpace, placeLabels, rectsOverlap } from "./canvasLabelSpace.ts";
import type { LabelBid } from "./canvasLabelSpace.ts";

/** A 100x20 rectangle at (x, y), so collisions are easy to arrange on purpose. */
const rect = (x: number, y: number) =>
  ({ left: x, right: x + 100, top: y, bottom: y + 20 });

const bid = (id: string, x: number, y: number,
             extra: Partial<LabelBid> = {}): LabelBid =>
  ({ id, rect: rect(x, y), priority: 0, ...extra });

test("touching edges is not overlapping", () => {
  assert.equal(rectsOverlap(rect(0, 0), rect(100, 0)), false);
  assert.equal(rectsOverlap(rect(0, 0), rect(99, 0)), true);
});

test("a claimed rectangle turns the next one away", () => {
  const space = new LabelSpace();

  assert.equal(space.claim(rect(0, 0)), true);
  assert.equal(space.claim(rect(10, 0)), false);
  assert.equal(space.claim(rect(200, 0)), true);
});

test("a refused claim reserves nothing", () => {
  const space = new LabelSpace();
  space.claim(rect(0, 0));
  space.claim(rect(10, 0));

  // The refused rectangle must not block a third that only overlapped it.
  assert.equal(space.claim(rect(10, 40)), true);
});

test("reset frees the whole frame", () => {
  const space = new LabelSpace();
  space.claim(rect(0, 0));
  space.reset();

  assert.equal(space.claim(rect(0, 0)), true);
});

test("a reserved rectangle blocks others without being asked to fit", () => {
  const space = new LabelSpace();
  space.reserve(rect(0, 0));

  assert.equal(space.claim(rect(10, 0)), false);
});

test("band size is a speed knob, not a correctness one", () => {
  // The first rectangle sets the band height; a much taller one after it must
  // still collide correctly rather than slipping between bands.
  const space = new LabelSpace();
  space.claim({ left: 0, right: 100, top: 0, bottom: 2 });

  assert.equal(space.collides({ left: 0, right: 100, top: -500, bottom: 500 }), true);
});

test("a collision that straddles a band boundary is still a collision", () => {
  const space = new LabelSpace();
  space.claim(rect(0, 15));

  assert.equal(space.claim(rect(0, 25)), false);
});

test("labels that do not collide are all placed", () => {
  const chosen = placeLabels([bid("a", 0, 0), bid("b", 200, 0), bid("c", 400, 0)]);

  assert.deepEqual([...chosen].sort(), ["a", "b", "c"]);
});

test("the higher priority keeps the rectangle it contests", () => {
  const chosen = placeLabels([
    bid("loser", 0, 0, { priority: 1 }),
    bid("winner", 10, 0, { priority: 9 }),
  ]);

  assert.deepEqual([...chosen], ["winner"]);
});

test("a pinned label outranks every priority and displaces what it covers", () => {
  const chosen = placeLabels([
    bid("other", 0, 0, { priority: 9 }),
    bid("focused", 10, 0, { priority: 0, pinned: true }),
  ]);

  assert.deepEqual([...chosen], ["focused"]);
});

test("two pinned labels are both drawn even against each other", () => {
  const chosen = placeLabels([
    bid("a", 0, 0, { pinned: true }),
    bid("b", 10, 0, { pinned: true }),
  ]);

  assert.deepEqual([...chosen].sort(), ["a", "b"]);
});

test("equal priorities resolve by id, so a settled map does not flicker", () => {
  const first = placeLabels([bid("zzz", 0, 0), bid("aaa", 10, 0)]);
  const again = placeLabels([bid("aaa", 10, 0), bid("zzz", 0, 0)]);

  assert.deepEqual([...first], ["aaa"]);
  assert.deepEqual([...first], [...again]);
});

test("nothing to place is not an error", () => {
  assert.equal(placeLabels([]).size, 0);
});
