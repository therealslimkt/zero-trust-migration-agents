import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { test } from "vitest";

interface AgentEntry {
  id: string;
  name: string;
  path: string;
}

const repositoryRoot = resolve(process.cwd(), "..");
const requiredFiles = [
  "AGENT.md",
  "AGENTS.md",
  "agent.card.json",
  "routing.json",
  "policy.json",
  "schemas/input.schema.json",
  "schemas/output.schema.json",
  "schemas/state.schema.json",
  "tools/mcp.json",
  "memory/README.md",
  "artifacts/README.md",
  "evals/rubric.yaml",
  "examples/README.md",
  "tests/README.md",
];

async function verifyManifest(relativeManifestPath: string, expectedRoot: string): Promise<void> {
  const manifest = JSON.parse(await readFile(resolve(repositoryRoot, relativeManifestPath), "utf8")) as { agents: Record<string, AgentEntry> };
  for (const [key, agent] of Object.entries(manifest.agents)) {
    assert.equal(key, agent.id);
    assert.equal(agent.path, `${expectedRoot}/${key}`);
    assert.equal(agent.id.startsWith("the_"), false);
    assert.equal(agent.name.startsWith("The "), false);
    await Promise.all(requiredFiles.map((file) => access(resolve(repositoryRoot, agent.path, file))));
  }
}

test("build manifest resolves every canonical scaffold", () => verifyManifest(
  "plan/agents/build_agents/build_agent_manifest.json",
  "plan/agents/build_agents",
));

test("product manifest resolves every canonical scaffold", () => verifyManifest(
  "plan/agents/product_agents/product_agent_manifest.json",
  "plan/agents/product_agents",
));
