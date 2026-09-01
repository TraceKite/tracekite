import assert from "node:assert/strict";
import test from "node:test";

import { summarizeCoverage } from "./coverageSummary.ts";

test("coverage totals remain totals instead of being mislabeled as languages", () => {
  assert.deepEqual(summarizeCoverage({
    files_seen: 20,
    files_parsed: 15,
    parse_errors: 2,
    endpoints_computed_path: 3,
    endpoints: 0,
  }), {
    filesSeen: 20,
    filesParsed: 15,
    percentage: 75,
    counters: [
      { label: "endpoints computed path", value: 3 },
      { label: "parse errors", value: 2 },
    ],
  });
});

test("missing file totals are reported as unrecorded, not zero percent", () => {
  assert.equal(summarizeCoverage({}).percentage, null);
});
