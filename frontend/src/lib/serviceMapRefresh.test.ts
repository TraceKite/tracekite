import assert from "node:assert/strict";
import test from "node:test";

import { observeLinkRun } from "./serviceMapRefresh.ts";

test("a newly completed observed link run refreshes the service map once", () => {
  const running = observeLinkRun(null, { id: "run-2", status: "running" });
  const done = observeLinkRun(running.activeRunId, { id: "run-2", status: "done" });
  const repeated = observeLinkRun(done.activeRunId, { id: "run-2", status: "done" });

  assert.deepEqual(running, { activeRunId: "run-2", refresh: false });
  assert.deepEqual(done, { activeRunId: null, refresh: true });
  assert.deepEqual(repeated, { activeRunId: null, refresh: false });
});

test("old and failed link runs do not refresh the service map", () => {
  assert.equal(observeLinkRun(null, { id: "old", status: "done" }).refresh, false);
  assert.deepEqual(observeLinkRun("run-3", { id: "run-3", status: "failed" }), {
    activeRunId: null,
    refresh: false,
  });
});
