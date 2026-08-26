import type { FastifyInstance } from "fastify";

import type { OrchestratorServices } from "../services.js";

export async function registerAgentRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/agents", async () => ({ data: services.agents }));
}

