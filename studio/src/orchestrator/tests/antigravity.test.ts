import assert from "node:assert/strict";
import { test } from "vitest";

import { buildAntigravityArgs } from "../providers/antigravity.js";

test("Antigravity headless args bind the prompt immediately after --print", () => {
  const args = buildAntigravityArgs("review payload", "gemini-3.7-flash-high", 120_000);
  assert.deepEqual(args.slice(0, 2), ["--print", "review payload"]);
  assert.equal(args[args.indexOf("--effort") + 1], "high");
  assert.equal(args[args.indexOf("--mode") + 1], "plan");
  assert.equal(args.includes("--dangerously-skip-permissions"), false);
});

test("Antigravity headless args reject models without an effort suffix", () => {
  assert.throws(() => buildAntigravityArgs("review payload", "gemini-custom"), /effort suffix/);
});
