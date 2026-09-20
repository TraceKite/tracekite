import assert from "node:assert/strict";
import test from "node:test";

import { trimLinkToNodes } from "./serviceMapLinkGeometry.ts";

/** The zoom a fitted 55-node map settles on, and the layout's link distance. */
const FITTED_SCALE = 0.1545;
const LINK_DISTANCE = 130;

const nodeTrim = (globalScale: number) => ({
  startClearancePx: 12,
  endClearancePx: 14,
  arrowPx: 7,
  globalScale,
});

test("a link shorter than its own clearances is still drawn", () => {
  const line = trimLinkToNodes(
    { x: 0, y: 0 }, { x: LINK_DISTANCE, y: 0 }, nodeTrim(FITTED_SCALE));

  assert.ok(line, "the fitted map's typical link must produce a line");
  // Clearances alone want ~168 units here, more than the 130 available.
  assert.ok(line.ex > line.sx, "the line must run from source towards target");
  const drawn = line.ex - line.sx;
  assert.ok(drawn >= LINK_DISTANCE * 0.3 - 1e-9,
            `expected at least 30% drawn, got ${drawn} of ${LINK_DISTANCE}`);
});

test("clearances keep their proportion to each other when they shrink", () => {
  const line = trimLinkToNodes(
    { x: 0, y: 0 }, { x: LINK_DISTANCE, y: 0 }, nodeTrim(FITTED_SCALE));

  assert.ok(line);
  const startGap = line.sx;
  const endGap = LINK_DISTANCE - line.ex;
  // 12px against 14px, whatever the shrink factor turned out to be.
  assert.ok(Math.abs(startGap / endGap - 12 / 14) < 1e-9);
});

test("a link with room to spare keeps the full clearance", () => {
  const scale = 1;
  const line = trimLinkToNodes({ x: 0, y: 0 }, { x: 400, y: 0 }, nodeTrim(scale));

  assert.ok(line);
  assert.equal(line.sx, 12);
  assert.equal(line.ex, 400 - 14);
  assert.equal(line.arrowLength, 7);
});

test("the arrowhead never outgrows the line it sits on", () => {
  const line = trimLinkToNodes(
    { x: 0, y: 0 }, { x: LINK_DISTANCE, y: 0 }, nodeTrim(FITTED_SCALE));

  assert.ok(line);
  assert.ok(line.arrowLength <= (line.ex - line.sx) * 0.5 + 1e-9,
            "an arrowhead over half the line reads as a triangle");
});

test("coincident nodes have no line to draw", () => {
  assert.equal(
    trimLinkToNodes({ x: 5, y: 5 }, { x: 5, y: 5 }, nodeTrim(FITTED_SCALE)), null);
});

test("a zoom of zero declines rather than dividing by it", () => {
  assert.equal(trimLinkToNodes({ x: 0, y: 0 }, { x: 100, y: 0 }, nodeTrim(0)), null);
});

test("trimming holds on a diagonal, not just an axis", () => {
  const line = trimLinkToNodes({ x: 0, y: 0 }, { x: 300, y: 400 }, nodeTrim(1));

  assert.ok(line);
  // 3-4-5: the start clearance of 12 lands 12 units along a length-500 span.
  assert.ok(Math.abs(Math.hypot(line.sx, line.sy) - 12) < 1e-9);
  assert.ok(Math.abs(Math.hypot(300 - line.ex, 400 - line.ey) - 14) < 1e-9);
});
