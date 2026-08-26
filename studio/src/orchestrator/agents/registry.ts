import { readFile } from "node:fs/promises";

import { CONTROL_SCHEMA_VERSION, type AgentSummary } from "../../control/contracts.generated.js";

interface ManifestAgent {
  id: AgentSummary["id"];
  name: string;
  modelPolicy: string;
}

interface Manifest {
  agents: Record<string, ManifestAgent>;
}

async function loadManifest(path: string, kind: AgentSummary["kind"]): Promise<AgentSummary[]> {
  const manifest = JSON.parse(await readFile(path, "utf8")) as Manifest;
  return Object.values(manifest.agents).map((agent) => ({
    schemaVersion: CONTROL_SCHEMA_VERSION,
    id: agent.id,
    displayName: agent.name,
    kind,
    status: "idle",
    modelPolicy: agent.modelPolicy,
    activeProvider: null,
    activeModel: null,
    currentTaskId: null,
    workspace: null,
    contextScope: [],
  }));
}

export async function loadAgentRegistry(buildManifestPath: string, productManifestPath: string): Promise<AgentSummary[]> {
  const [buildAgents, productAgents] = await Promise.all([
    loadManifest(buildManifestPath, "build"),
    loadManifest(productManifestPath, "product"),
  ]);
  return [...buildAgents, ...productAgents];
}
