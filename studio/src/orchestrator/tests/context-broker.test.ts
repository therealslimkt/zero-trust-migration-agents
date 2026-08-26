import assert from "node:assert/strict";
import { mkdtemp, mkdir, realpath, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { onTestFinished, test } from "vitest";

import { ContextBroker, isProtectedRelativePath } from "../context/broker.ts";

test("protected path classification is deny-by-default", () => {
  assert.equal(isProtectedRelativePath(".env"), true);
  assert.equal(isProtectedRelativePath(".env.local"), true);
  assert.equal(isProtectedRelativePath(".env.example"), false);
  assert.equal(isProtectedRelativePath("plan/agents/product_agents/piano_man/context/song.md"), true);
  assert.equal(isProtectedRelativePath("research/audio/reference.md"), true);
  assert.equal(isProtectedRelativePath("src/private/key.txt"), true);
  assert.equal(isProtectedRelativePath("skin/src/studio/App.tsx"), false);
});

test("broker accepts scoped files and rejects traversal, protected paths, and symlink escape", async () => {
  const sandbox = await mkdtemp(join(tmpdir(), "skin-context-broker-"));
  const repositoryRoot = join(sandbox, "repository");
  const outsideRoot = join(sandbox, "outside");
  await mkdir(join(repositoryRoot, "allowed"), { recursive: true });
  await mkdir(join(repositoryRoot, "plan/agents/product_agents/piano_man/context"), { recursive: true });
  await mkdir(outsideRoot, { recursive: true });
  await writeFile(join(repositoryRoot, "allowed/data.txt"), "allowed", "utf8");
  await writeFile(join(repositoryRoot, "plan/agents/product_agents/piano_man/context/song.md"), "protected", "utf8");
  await writeFile(join(outsideRoot, "escape.txt"), "outside", "utf8");
  await symlink(outsideRoot, join(repositoryRoot, "allowed/escape"));
  onTestFinished(() => rm(sandbox, { recursive: true, force: true }));

  const broker = await ContextBroker.create(repositoryRoot);
  const scope = {
    readAllowlist: ["allowed/**"],
    readDenylist: [],
    writeAllowlist: ["allowed/**"],
  };

  const allowed = await broker.authorizeRead("allowed/data.txt", scope);
  assert.equal(allowed.allowed, true);
  assert.equal(allowed.canonicalPath, await realpath(join(repositoryRoot, "allowed/data.txt")));
  assert.equal((await broker.authorizeRead("../../escape.txt", scope)).reason, "path_escape");
  assert.equal((await broker.authorizeRead("plan/agents/product_agents/piano_man/context/song.md", {
    ...scope,
    readAllowlist: ["plan/agents/product_agents/piano_man/context/**"],
  })).reason, "protected_context_requires_grant");
  assert.equal((await broker.authorizeRead("plan/agents/product_agents/piano_man/context/song.md", {
    ...scope,
    readAllowlist: ["plan/agents/product_agents/piano_man/context/**"],
    grantedProtectedPaths: ["plan/agents/product_agents/piano_man/context/song.md"],
  })).allowed, true);
  assert.equal((await broker.authorizeRead("allowed/escape/escape.txt", scope)).reason, "symlink_escape");
});
