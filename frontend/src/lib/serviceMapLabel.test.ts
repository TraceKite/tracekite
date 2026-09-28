import assert from "node:assert/strict";
import test from "node:test";

import {
  bareServiceName,
  fitServiceLabel,
  MAX_SERVICE_LABEL_PX,
  serviceDisplayNames,
} from "./serviceMapLabel.ts";

/** Stand-in for canvas metrics: every glyph is 7px at the paint font. */
const measure = (text: string) => text.length * 7;

test("a repo-qualified name reduces to the service it names", () => {
  assert.equal(
    bareServiceName("spring-petclinic_spring-petclinic-microservices/tracing-server"),
    "tracing-server",
  );
  assert.equal(bareServiceName("api-gateway"), "api-gateway");
});

test("an unambiguous service drops its repo qualifier", () => {
  const names = serviceDisplayNames([
    { id: "a", name: "repo-one/tracing-server" },
    { id: "b", name: "repo-one/grafana-server" },
  ]);
  assert.equal(names.get("a"), "tracing-server");
  assert.equal(names.get("b"), "grafana-server");
});

test("two repos contributing the same service name stay told apart", () => {
  const names = serviceDisplayNames([
    { id: "a", name: "repo-one/config-server" },
    { id: "b", name: "repo-two/config-server" },
  ]);
  // Collapsing these to one label would draw two different services under one
  // name, which is worse than a long one. What they share carries no
  // information by construction, so only what differs is kept.
  assert.equal(names.get("a"), "one/config-server");
  assert.equal(names.get("b"), "two/config-server");
  assert.notEqual(names.get("a"), names.get("b"));
});

test("a qualifier is trimmed to what differs, not to what fits", () => {
  // Two repos in one organisation share nearly all of their id, and the few
  // characters that differ sit in the middle — exactly where fitServiceLabel
  // cuts. The map drew three pairs of identical names over six services.
  const names = serviceDisplayNames([
    { id: "a", name: "spring-petclinic_spring-petclinic-cloud/grafana-server" },
    { id: "b", name: "spring-petclinic_spring-petclinic-microservices/grafana-server" },
  ]);

  assert.equal(names.get("a"), "cloud/grafana-server");
  assert.equal(names.get("b"), "microservices/grafana-server");
});

test("a shared run with no separator in it is left whole", () => {
  // Trimming here would serve `def` and `xyz`, which are not names.
  const names = serviceDisplayNames([
    { id: "a", name: "abcdef/config-server" },
    { id: "b", name: "abcxyz/config-server" },
  ]);

  assert.equal(names.get("a"), "abcdef/config-server");
  assert.equal(names.get("b"), "abcxyz/config-server");
});

test("trimming never makes two different qualifiers read the same", () => {
  // The shared run is `org-`; dropping it and the leading separator it leaves
  // behind turns both into `x`, which would draw two services under one name.
  const names = serviceDisplayNames([
    { id: "a", name: "org-x/api" },
    { id: "b", name: "org--x/api" },
  ]);

  assert.notEqual(names.get("a"), names.get("b"));
  assert.equal(names.get("a"), "org-x/api");
  assert.equal(names.get("b"), "org--x/api");
});

test("an unqualified name colliding with a qualified one is not shortened away", () => {
  const names = serviceDisplayNames([
    { id: "a", name: "config-server" },
    { id: "b", name: "repo-two/config-server" },
  ]);
  assert.equal(names.get("a"), "config-server");
  assert.equal(names.get("b"), "repo-two/config-server");
});

test("a label that already fits is left exactly as it is", () => {
  assert.equal(fitServiceLabel("api-gateway", MAX_SERVICE_LABEL_PX, measure), "api-gateway");
});

test("an oversized label is cut from the middle and fits the budget", () => {
  const label = "spring-petclinic_spring-petclinic-microservices/tracing-server";
  const shown = fitServiceLabel(label, MAX_SERVICE_LABEL_PX, measure);
  assert.equal(measure(shown) <= MAX_SERVICE_LABEL_PX, true);
  assert.match(shown, /…/);
  // Both ends survive: the head says which repo, the tail says which service.
  assert.equal(shown.startsWith("spring"), true);
  assert.equal(shown.endsWith("server"), true);
});

test("the widest label that fits is chosen, not merely one that does", () => {
  const label = "abcdefghijklmnopqrstuvwxyz";
  const shown = fitServiceLabel(label, 10 * 7, measure);
  assert.equal(measure(shown) <= 70, true);
  assert.equal(measure(shown + "x") > 70, true);
});

test("a budget too small for any pair of characters degrades to the ellipsis", () => {
  assert.equal(fitServiceLabel("tracing-server", 7, measure), "…");
});

test("an absent budget leaves the label alone rather than erasing it", () => {
  assert.equal(fitServiceLabel("tracing-server", 0, measure), "tracing-server");
});
