import assert from "node:assert/strict";
import test from "node:test";

import {
  estimateLabelWidth,
  MAX_LABEL_WIDTH,
  shouldExposeLabel,
} from "./graph3dLabelPlacer.ts";

test("only visible or investigation-critical 3D labels enter keyboard navigation", () => {
  assert.equal(shouldExposeLabel(true, false), true);
  assert.equal(shouldExposeLabel(false, true), true);
  assert.equal(shouldExposeLabel(false, false), false);
});

test("label width used for collision bounds matches the DOM cap", () => {
  assert.equal(estimateLabelWidth("short") >= 48, true);
  assert.equal(estimateLabelWidth("x".repeat(200)), MAX_LABEL_WIDTH);
});
