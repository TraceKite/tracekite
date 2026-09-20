import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";

/** React refuses to boot on a react/react-dom mismatch, and says so only in
 * the browser console — as minified error #527, on a page that renders
 * nothing. Typecheck passes, every other test passes, and the build succeeds:
 * the whole app is blank and nothing before the browser noticed.
 *
 * It reached main because the two are bumped as separate catalog entries and
 * only react moved, so this asserts the pair a partial bump breaks. The
 * installed versions rather than the declared ranges, because what React
 * compares at runtime is what resolution actually produced. */
test("react and react-dom are the exact same version", () => {
  const require = createRequire(import.meta.url);
  const react = require("react/package.json").version;
  const reactDom = require("react-dom/package.json").version;

  assert.equal(reactDom, react,
               `react ${react} against react-dom ${reactDom}: React throws #527 `
               + "and renders nothing. Move both catalog entries together.");
});
