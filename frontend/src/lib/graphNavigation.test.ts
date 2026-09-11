import assert from "node:assert/strict";
import test from "node:test";

import {
  activeNavigation,
  cameraSceneKey,
  effectiveRepoIds,
  graphContextKey,
  synchronizeGraphContext,
  toggleDraftRepoScope,
} from "./graphNavigation.ts";

const repo = (id: string) => ({ id } as any);

test("graph context survives a 2D/3D renderer switch but resets for a new view", () => {
  const key = graphContextKey(["b", "a"], "overview");
  const context = { contextKey: key, expandedGroup: "a/root", expandedNodeId: "a:main.py" };
  assert.deepEqual(activeNavigation(context, graphContextKey(["a", "b"], "overview")), {
    expandedGroup: "a/root",
    expandedNodeId: "a:main.py",
  });
  // A different view draws a different set, so neither level survives it.
  assert.deepEqual(activeNavigation(context, graphContextKey(["a", "b"], "code")), {
    expandedGroup: null,
    expandedNodeId: null,
  });
  assert.deepEqual(synchronizeGraphContext(context, graphContextKey(["a", "b"], "code")), {
    contextKey: "a,b|code",
    expandedGroup: null,
    expandedNodeId: null,
  });
});

test("repository selection can be cleared back to every repository", () => {
  assert.deepEqual(toggleDraftRepoScope([], "a", 2), ["a"]);
  assert.deepEqual(toggleDraftRepoScope(["a"], "a", 2), []);
  assert.deepEqual(toggleDraftRepoScope(["a"], "b", 2), ["a", "b"]);
  assert.deepEqual(toggleDraftRepoScope(["a", "b"], "c", 2), ["a", "b"]);
  assert.deepEqual(toggleDraftRepoScope(["a", "b"], "a", 2), ["b"]);
});

test("empty repository scope consistently means every loaded repository", () => {
  assert.deepEqual(effectiveRepoIds([repo("a"), repo("b")], [], repo("a")), ["a", "b"]);
  assert.deepEqual(effectiveRepoIds([repo("a"), repo("b")], ["b"], repo("a")), ["b"]);
});

test("the camera frames a scene, and a selection is not one", () => {
  const scene = {
    repoIds: ["b", "a"],
    viewMode: "overview" as const,
    focusNodeId: null,
    expandedGroup: null,
  };
  assert.equal(cameraSceneKey(scene), cameraSceneKey({ ...scene, repoIds: ["a", "b"] }));
  for (const rebuilt of [
    { ...scene, viewMode: "code" as const },
    { ...scene, expandedGroup: "a/api" },
    { ...scene, focusNodeId: "a:src/main.py" },
    { ...scene, layout: "sphere" },
  ]) {
    assert.notEqual(cameraSceneKey(scene), cameraSceneKey(rebuilt));
  }
});
