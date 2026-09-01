import assert from "node:assert/strict";
import test from "node:test";

import {
  activeExpandedGroup,
  effectiveRepoIds,
  graphContextKey,
  synchronizeGraphContext,
  toggleDraftRepoScope,
} from "./graphNavigation.ts";

const repo = (id: string) => ({ id } as any);

test("graph context survives a 2D/3D renderer switch but resets for a new view", () => {
  const key = graphContextKey(["b", "a"], "overview");
  const context = { contextKey: key, expandedGroup: "a/root" };
  assert.equal(activeExpandedGroup(context, graphContextKey(["a", "b"], "overview")), "a/root");
  assert.deepEqual(synchronizeGraphContext(context, graphContextKey(["a", "b"], "code")), {
    contextKey: "a,b|code",
    expandedGroup: null,
  });
});

test("repository selection is staged without an ambiguous empty custom scope", () => {
  assert.deepEqual(toggleDraftRepoScope([], "a", 2), ["a"]);
  assert.deepEqual(toggleDraftRepoScope(["a"], "a", 2), ["a"]);
  assert.deepEqual(toggleDraftRepoScope(["a"], "b", 2), ["a", "b"]);
  assert.deepEqual(toggleDraftRepoScope(["a", "b"], "c", 2), ["a", "b"]);
  assert.deepEqual(toggleDraftRepoScope(["a", "b"], "a", 2), ["b"]);
});

test("empty repository scope consistently means every loaded repository", () => {
  assert.deepEqual(effectiveRepoIds([repo("a"), repo("b")], [], repo("a")), ["a", "b"]);
  assert.deepEqual(effectiveRepoIds([repo("a"), repo("b")], ["b"], repo("a")), ["b"]);
});
