import assert from "node:assert/strict";
import { test } from "vitest";

import { agentHref, parseStudioHash } from "./router.js";

test("Studio hashes resolve distinct sections", () => {
  assert.deepEqual(parseStudioHash("#/context"), { section: "context", agentId: null });
  assert.deepEqual(parseStudioHash("#/artifacts"), { section: "artifacts", agentId: null });
  assert.deepEqual(parseStudioHash("#/missing"), { section: "overview", agentId: null });
});

test("agent routes preserve the selected canonical id", () => {
  assert.equal(agentHref("critic_that_counts"), "#/agents/agent/critic_that_counts");
  assert.deepEqual(parseStudioHash("#/agents/agent/critic_that_counts"), {
    section: "agents",
    agentId: "critic_that_counts",
  });
});
