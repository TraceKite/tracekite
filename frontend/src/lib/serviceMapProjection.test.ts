import assert from "node:assert/strict";
import test from "node:test";

import { projectServiceMap, serviceMapEmptyState } from "./serviceMapProjection.ts";
import type { ServiceMapResponse } from "./types.ts";

const EDGE_TYPES = ["CALLS_SERVICE", "ROUTES_TO"];

function response(overrides: Partial<ServiceMapResponse> = {}): ServiceMapResponse {
  return {
    nodes: [
      { id: "svc:a", name: "a", kind: "service", repo_ids: ["repo-one"] },
      { id: "svc:b", name: "b", kind: "service", repo_ids: ["repo-one"] },
      { id: "svc:c", name: "c", kind: "service", repo_ids: ["repo-two"] },
    ],
    edges: [
      {
        source: "svc:a", target: "svc:b", type: "CALLS_SERVICE", confidence: 0.9,
        min_confidence: 0.9, max_confidence: 0.9, via: [], weight: 1, evidence: [],
        source_repo_id: "repo-one",
      },
    ],
    totals: { services: 3, edges: 1 },
    truncated: false,
    ...overrides,
  };
}

test("an unscoped projection keeps every service and its links", () => {
  const projected = projectServiceMap(response(), EDGE_TYPES, []);
  assert.deepEqual(projected.nodes.map((n) => n.id), ["svc:a", "svc:b", "svc:c"]);
  assert.equal(projected.links.length, 1);
  assert.equal(projected.isolated, 1);
});

test("scoping to one repo drops services built from another", () => {
  const projected = projectServiceMap(response(), EDGE_TYPES, ["repo-one"]);
  assert.deepEqual(projected.nodes.map((n) => n.id), ["svc:a", "svc:b"]);
});

test("disabling every link type leaves the in-scope services standing alone", () => {
  const data = response();
  const projected = projectServiceMap(data, [], ["repo-one"]);
  assert.equal(projected.links.length, 0);
  assert.equal(projected.isolated, 2);
  // Services without links are still the answer, so this is not an empty map.
  assert.equal(serviceMapEmptyState(data, projected, ["repo-one"]), null);
});

test("an edge attributed to another repo is not drawn into this scope", () => {
  const data = response();
  data.edges[0].source_repo_id = "repo-two";
  const projected = projectServiceMap(data, EDGE_TYPES, ["repo-one"]);
  assert.equal(projected.links.length, 0);
  assert.deepEqual(projected.nodes.map((n) => n.id), ["svc:a", "svc:b"]);
});

test("messaging edge types reach the canvas, not just the http ones", () => {
  const data = response({
    nodes: [
      { id: "svc:a", name: "a", kind: "service", repo_ids: ["repo-one"] },
      { id: "topic:t", name: "t", kind: "node", repo_ids: ["repo-one"] },
      { id: "svc:b", name: "b", kind: "service", repo_ids: ["repo-one"] },
    ],
    edges: [
      {
        source: "svc:a", target: "topic:t", type: "PUBLISHES_TO", confidence: 0.9,
        min_confidence: 0.9, max_confidence: 0.9, via: [], weight: 1, evidence: [],
      },
      {
        source: "svc:b", target: "topic:t", type: "CONSUMES_FROM", confidence: 0.9,
        min_confidence: 0.9, max_confidence: 0.9, via: [], weight: 1, evidence: [],
      },
    ],
  });
  const projected = projectServiceMap(
    data, ["PUBLISHES_TO", "CONSUMES_FROM", "FANS_OUT_TO"], []);
  assert.equal(projected.links.length, 2);
  // The topic node is drawn because an edge reaches it, not because it is a
  // service — that is what keeps rendezvous nodes out of an unlinked map.
  assert.deepEqual(projected.nodes.map((n) => n.id).sort(), ["svc:a", "svc:b", "topic:t"]);
});

test("an edge with no repo attribution survives scoping", () => {
  const data = response();
  delete data.edges[0].source_repo_id;
  const projected = projectServiceMap(data, EDGE_TYPES, ["repo-one"]);
  assert.equal(projected.links.length, 1);
});

test("each projection owns its arrays, because force-graph mutates them", () => {
  const first = projectServiceMap(null, EDGE_TYPES, []);
  const second = projectServiceMap(null, EDGE_TYPES, []);
  assert.notEqual(first.nodes, second.nodes);
  assert.notEqual(first.links, second.links);
});

test("unconnected services are pinned in a row centred on the origin", () => {
  const projected = projectServiceMap(response(), [], []);
  const pinned = projected.nodes.filter((n) => n.fx != null);
  assert.equal(pinned.length, 3);
  assert.deepEqual(pinned.map((n) => n.fy), [180, 180, 180]);
  // Symmetric about zero, so zoomToFit does not favour one end of the row.
  assert.equal(pinned.reduce((sum, n) => sum + (n.fx ?? 0), 0), 0);
  // Wide enough that a bare service name does not clip its neighbour.
  const gaps = pinned.slice(1).map((n, i) => (n.fx ?? 0) - (pinned[i].fx ?? 0));
  assert.deepEqual(gaps, [150, 150]);
});

test("a scope with no resolved services explains that the services are elsewhere", () => {
  const data = response();
  const projected = projectServiceMap(data, EDGE_TYPES, ["repo-unrelated"]);
  assert.equal(projected.nodes.length, 0);
  const empty = serviceMapEmptyState(data, projected, ["repo-unrelated"]);
  assert.equal(empty?.title, "No services in this scope");
  assert.match(empty?.detail ?? "", /3 services/);
});

test("an estate with no resolved services is reported as such, not as a scope problem", () => {
  const data = response({ nodes: [], edges: [], totals: { services: 0, edges: 0 } });
  const projected = projectServiceMap(data, EDGE_TYPES, []);
  assert.equal(serviceMapEmptyState(data, projected, [])?.title, "No services resolved");
});

test("an unloaded map declines to claim it is empty", () => {
  const projected = projectServiceMap(null, EDGE_TYPES, []);
  assert.deepEqual(projected, { nodes: [], links: [], dangling: 0, isolated: 0 });
  assert.equal(serviceMapEmptyState(null, projected, []), null);
});
