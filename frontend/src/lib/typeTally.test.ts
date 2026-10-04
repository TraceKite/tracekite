import assert from "node:assert/strict";
import test from "node:test";

import { tallyTypes } from "./typeTally.ts";

const links = [
  { type: "CONTAINS" }, { type: "DECLARES" }, { type: "CONTAINS" },
  { type: "EXPOSES_API" }, { type: "CONTAINS" },
];

test("lists only types the view returned, most frequent first", () => {
  assert.deepEqual(tallyTypes(links, []), [
    { type: "CONTAINS", count: 3 },
    { type: "DECLARES", count: 1 },
    { type: "EXPOSES_API", count: 1 },
  ]);
});

test("a type the backend never writes is not listed as a zero", () => {
  const listed = tallyTypes(links, []).map((row) => row.type);
  assert.ok(!listed.includes("IMPORTS"));
  assert.ok(!listed.includes("CALLS_API"));
});

test("a hidden type stays listed after switching to a view without it", () => {
  // Hidden in the API view, then the user moves to Dependencies: it must
  // still be there to show again, honestly counted.
  assert.deepEqual(tallyTypes([{ type: "DEPENDS_ON" }], ["CALLS"]), [
    { type: "DEPENDS_ON", count: 1 },
    { type: "CALLS", count: 0 },
  ]);
});
