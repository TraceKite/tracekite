import assert from "node:assert/strict";
import test from "node:test";

import { shouldExposeLabel } from "./graph3dLabelPlacer.ts";

test("only visible or investigation-critical 3D labels enter keyboard navigation", () => {
  assert.equal(shouldExposeLabel(true, false), true);
  assert.equal(shouldExposeLabel(false, true), true);
  assert.equal(shouldExposeLabel(false, false), false);
});
