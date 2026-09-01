import assert from "node:assert/strict";
import test from "node:test";

import { MAX_FIT_ZOOM, fitTarget } from "./graphCameraFit.ts";

const viewport = { width: 1028, height: 675 };

test("the fit frames the drawn graph on its tighter axis", () => {
  // 888 usable px over 600 units, against 535 over 400: height binds.
  const target = fitTarget({ x: [-300, 300], y: [-100, 300] }, viewport, 70);
  assert.deepEqual({ x: target?.x, y: target?.y }, { x: 0, y: 100 });
  assert.equal(target?.zoom, (675 - 140) / 400);
});

test("a module holding one node does not become a microscope", () => {
  const single = fitTarget({ x: [-4, 4], y: [-4, 4] }, viewport, 70);
  assert.equal(single?.zoom, MAX_FIT_ZOOM);
  assert.deepEqual({ x: single?.x, y: single?.y }, { x: 0, y: 0 });
});

test("a viewport with no room to draw in is not framed at all", () => {
  assert.equal(fitTarget({ x: [-100, 100], y: [-50, 50] }, { width: 0, height: 0 }, 70), null);
  assert.equal(fitTarget(null, viewport, 70), null);
});
