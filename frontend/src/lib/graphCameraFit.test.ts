import assert from "node:assert/strict";
import test from "node:test";

import { MAX_FIT_ZOOM, fitTarget, frameGraph } from "./graphCameraFit.ts";

const viewport = { width: 1028, height: 675 };

test("the fit frames the drawn graph on its tighter axis", () => {
  // 888 usable px over 600 units, against 535 over 400: height binds.
  const target = fitTarget({ x: [-300, 300], y: [-100, 300] }, viewport, { padding: 70 });
  assert.deepEqual({ x: target?.x, y: target?.y }, { x: 0, y: 100 });
  assert.equal(target?.zoom, (675 - 140) / 400);
});

test("a module holding one node does not become a microscope", () => {
  const single = fitTarget({ x: [-4, 4], y: [-4, 4] }, viewport, { padding: 70 });
  assert.equal(single?.zoom, MAX_FIT_ZOOM);
  assert.deepEqual({ x: single?.x, y: single?.y }, { x: 0, y: 0 });
});

test("a viewport with no room to draw in is not framed at all", () => {
  assert.equal(
    fitTarget({ x: [-100, 100], y: [-50, 50] }, { width: 0, height: 0 }, { padding: 70 }), null);
  assert.equal(fitTarget(null, viewport, { padding: 70 }), null);
});

test("the fit shrinks as far as the scene needs unless the caller sets a floor", () => {
  // A wide repo graph: 888 usable px over 8000 units is far below any floor.
  const wide = { x: [-4000, 4000] as [number, number], y: [-100, 100] as [number, number] };
  assert.equal(fitTarget(wide, viewport, { padding: 70 })?.zoom, 888 / 8000);
  assert.equal(fitTarget(wide, viewport, { padding: 70, minZoom: 0.3 })?.zoom, 0.3);
});

test("a floor never holds a scene that already fits above it", () => {
  const target = fitTarget({ x: [-300, 300], y: [-100, 300] }, viewport,
                           { padding: 70, minZoom: 0.3 });
  assert.equal(target?.zoom, (675 - 140) / 400);
});

test("framing moves the camera onto the fit, and declines when there is none", () => {
  const calls: string[] = [];
  const graph = {
    getGraphBbox: () => ({ x: [-300, 300] as [number, number], y: [-100, 300] as [number, number] }),
    centerAt: (x: number, y: number, ms?: number) => calls.push(`center ${x},${y} ${ms}`),
    zoom: (k: number, ms?: number) => calls.push(`zoom ${k} ${ms}`),
  };

  assert.equal(frameGraph(graph, viewport, { padding: 70, durationMs: 400 }), true);
  assert.deepEqual(calls, ["center 0,100 400", `zoom ${(675 - 140) / 400} 400`]);

  assert.equal(frameGraph(null, viewport, { padding: 70, durationMs: 400 }), false);
  assert.equal(frameGraph({ ...graph, getGraphBbox: () => null }, viewport,
                          { padding: 70, durationMs: 400 }), false);
  assert.equal(calls.length, 2, "a declined fit must not move the camera");
});
