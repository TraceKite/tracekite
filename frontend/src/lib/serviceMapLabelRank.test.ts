import assert from "node:assert/strict";
import test from "node:test";

import { placeLabels } from "./canvasLabelSpace.ts";
import { serviceLabelBid, serviceLabelRanks } from "./serviceMapLabelRank.ts";

/** Two rectangles that overlap, so exactly one of the two labels can be drawn. */
const contested = { left: 0, right: 100, top: 0, bottom: 20 };
const beside = { left: 10, right: 110, top: 0, bottom: 20 };

/** A hub with three links, a quiet service with one, and a gateway with one. */
const nodes = [{ id: "hub" }, { id: "quiet" }, { id: "gw", is_gateway: true },
               { id: "a" }, { id: "b" }];
const links = [
  { source: "hub", target: "a" },
  { source: "hub", target: "b" },
  { source: { id: "hub" }, target: { id: "quiet" } },
  { source: "gw", target: "a" },
];
const ranks = serviceLabelRanks(nodes, links);

test("the busier service ranks higher, whichever form its links arrive in", () => {
  // The third link carries node objects, as force-graph leaves it once drawn.
  assert.equal(ranks.get("hub"), 3);
  assert.equal(ranks.get("quiet"), 1);
});

test("a gateway outranks a busier service", () => {
  assert.ok((ranks.get("gw") ?? 0) > (ranks.get("hub") ?? 0));
});

test("with nothing focused, the hub keeps a spot it contests", () => {
  const chosen = placeLabels([
    serviceLabelBid("hub", contested, { ranks, lit: null }),
    serviceLabelBid("quiet", beside, { ranks, lit: null }),
  ]);

  assert.deepEqual([...chosen], ["hub"]);
});

test("while a service is focused, its lit neighbour beats a dimmed hub", () => {
  // The hub is not adjacent to the focus, so it is painted at 12% opacity: it
  // must not take the name of the service the reader is inspecting.
  const context = { ranks, focusId: "a", lit: new Set(["a", "quiet"]) };
  const chosen = placeLabels([
    serviceLabelBid("hub", contested, context),
    serviceLabelBid("quiet", beside, context),
  ]);

  assert.deepEqual([...chosen], ["quiet"]);
});

test("the focused and the hovered service are pinned, even when dimmed", () => {
  const context = { ranks, focusId: "a", hoverId: "hub", lit: new Set(["a"]) };

  assert.equal(serviceLabelBid("a", contested, context).pinned, true);
  assert.equal(serviceLabelBid("hub", contested, context).pinned, true);
  assert.equal(serviceLabelBid("quiet", contested, context).pinned, false);
});
