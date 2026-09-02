import assert from "node:assert/strict";
import test from "node:test";

import { graphGroupOf, moduleOf } from "./graphStyle.ts";

test("frontend module grouping matches the backend boundary rules", () => {
  assert.equal(moduleOf("package.json"), "");
  assert.equal(moduleOf("projects/foyer/src/app.ts"), "projects/foyer");
  assert.equal(moduleOf("src/main.ts"), "src");
  assert.equal(moduleOf("deploy/service.yaml"), "");
});

test("root folders become useful repo-qualified graph groups", () => {
  const group = graphGroupOf({
    id: "folder", type: "Folder", label: "backend", name: "backend",
    path: "backend", repo_id: "sfbayman_lanovyx", size: 8,
    group: "Folder", metadata: {},
  });
  assert.equal(group, "sfbayman/lanovyx/backend");
});
