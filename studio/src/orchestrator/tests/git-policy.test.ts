import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { test } from "vitest";

const policyPath = resolve(process.cwd(), "../plan/agents/orchestration/git_policy.json");

test("branch policy accepts canonical agent/body names", async () => {
  const policy = JSON.parse(await readFile(policyPath, "utf8")) as { branchPattern: string };
  const pattern = new RegExp(policy.branchPattern);
  assert.equal(pattern.test("mission_control/v2_bootstrap"), true);
  assert.equal(pattern.test("easter_bunny/cool_egg"), true);
  assert.equal(pattern.test("front_of_house/monitoring_dashboard"), true);
});

test("branch policy rejects legacy and unsafe forms", async () => {
  const policy = JSON.parse(await readFile(policyPath, "utf8")) as { branchPattern: string };
  const pattern = new RegExp(policy.branchPattern);
  assert.equal(pattern.test("main"), false);
  assert.equal(pattern.test("agent/task-123"), false);
  assert.equal(pattern.test("the_architect/new-api"), false);
  assert.equal(pattern.test("easter_bunny/../escape"), false);
});
