import assert from "node:assert/strict";
import test from "node:test";

import { stableJitter } from "./graphStablePosition.ts";

test("node jitter is stable across repeated layout initialization", () => {
  const first = [0, 1, 2].map((axis) => stableJitter("repo:File:src/app.ts", axis));
  const second = [0, 1, 2].map((axis) => stableJitter("repo:File:src/app.ts", axis));
  assert.deepEqual(first, second);
  assert.notEqual(first[0], first[1]);
});
