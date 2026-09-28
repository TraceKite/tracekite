import assert from "node:assert/strict";
import test from "node:test";

import { serviceMapForces } from "./serviceMapLayout.ts";

test("charge holds the voids between clusters open at every size", () => {
  // -300 let the map's many disconnected components pile into the middle.
  assert.equal(serviceMapForces(16).chargeStrength, -900);
  assert.equal(serviceMapForces(55).chargeStrength, -900);
});

test("link distance grows with the map rather than shrinking", () => {
  // The bug: 55 nodes used to get a SHORTER link distance than 20 did, so the
  // fitted zoom put them inside each other's discs.
  const small = serviceMapForces(20);
  const large = serviceMapForces(55);

  assert.ok(large.linkDistance > small.linkDistance,
            `55 nodes got ${large.linkDistance}, 20 nodes got ${small.linkDistance}`);
});

test("link distance has no step for a map to fall just short of", () => {
  // A threshold at 40 left 38 nodes on the flat value below it, where thirty
  // of sixty-eight drawn lines were still under ten pixels.
  for (let n = 30; n < 60; n++) {
    const step = serviceMapForces(n + 1).linkDistance - serviceMapForces(n).linkDistance;
    assert.ok(step > 0 && step < 50, `${n}->${n + 1} jumped by ${step}`);
  }
});

test("the measured sizes get the distances they were measured at", () => {
  // Retuned once the layout gained forceX/forceY containment. Containment
  // compacts the cloud, which raises the fitted zoom, which means the same
  // on-screen link length needs far fewer graph units: 590 became a hairball
  // of 194px edges, and 230 puts the median back at 69px.
  assert.equal(serviceMapForces(38).linkDistance, 196);
  assert.equal(serviceMapForces(55).linkDistance, 230);
});

test("a pathological node count is capped rather than run away", () => {
  assert.equal(serviceMapForces(100000).linkDistance, 1200);
});

test("the collide radius clears two discs without expanding the whole map", () => {
  const forces = serviceMapForces(55);

  // At 0.32 of the link distance this was a uniform expansion that zoomToFit
  // handed straight back, and the median drawn link got shorter.
  assert.ok(forces.collideRadius < forces.linkDistance * 0.2,
            `${forces.collideRadius} against a ${forces.linkDistance} link is an expansion`);
  assert.ok(forces.collideRadius > 0);
});

test("an empty map still produces usable forces", () => {
  const forces = serviceMapForces(0);

  assert.ok(forces.linkDistance > 0);
  assert.ok(forces.chargeStrength < 0);
  assert.ok(forces.collideRadius > 0);
});
