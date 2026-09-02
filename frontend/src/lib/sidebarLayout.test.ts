import assert from "node:assert/strict";
import test from "node:test";

import { sidebarCollapsed, sidebarPressure } from "./sidebarLayout.ts";

test("the panel yields to the canvas only when the width runs out", () => {
  assert.equal(sidebarPressure(1440, false), false);
  assert.equal(sidebarPressure(1440, true), false);
  // A details drawer takes its width out of the canvas, not out of nowhere.
  assert.equal(sidebarPressure(1280, false), false);
  assert.equal(sidebarPressure(1280, true), true);
  assert.equal(sidebarPressure(900, false), true);
});

test("a reader's choice decides the layout it was made in, and only that one", () => {
  assert.equal(sidebarCollapsed(true, null), true);
  assert.equal(sidebarCollapsed(false, null), false);
  // Collapsed by hand with room to spare, and it survives a drawer opening and
  // closing again rather than springing back open.
  assert.equal(sidebarCollapsed(false, { collapsed: true, pressure: false }), true);
  // Held open by hand on a cramped layout.
  assert.equal(sidebarCollapsed(true, { collapsed: false, pressure: true }), false);
  // Neither choice speaks for the other layout: there, the rule decides.
  assert.equal(sidebarCollapsed(true, { collapsed: false, pressure: false }), true);
  assert.equal(sidebarCollapsed(false, { collapsed: true, pressure: true }), false);
});
