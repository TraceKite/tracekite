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

test("two repos contributing the same service name both keep their qualifier", () => {
  const names = serviceDisplayNames([
    { id: "a", name: "repo-one/config-server" },
    { id: "b", name: "repo-two/config-server" },
  ]);
  // Shortening here would draw two different services with one identical
  // label, which is worse than a long one.
  assert.equal(names.get("a"), "repo-one/config-server");
  assert.equal(names.get("b"), "repo-two/config-server");
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
