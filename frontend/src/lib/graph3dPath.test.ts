import assert from "node:assert/strict";
import test from "node:test";

import { findDirectedPath, isEdgeInPath } from "./graph3dPath.ts";

const links = [
  { source: "a", target: "b", type: "CALLS" },
  { source: "b", target: "c", type: "DEPENDS_ON" },
] as any[];

test("canvas paths follow asserted edge direction", () => {
  assert.deepEqual(findDirectedPath("a", "c", links), ["a", "b", "c"]);
  assert.equal(findDirectedPath("c", "a", links), null);
});

test("path highlighting cannot mark a reverse edge", () => {
  assert.equal(isEdgeInPath(links[0], ["a", "b"]), true);
  assert.equal(isEdgeInPath(links[0], ["b", "a"]), false);
});
