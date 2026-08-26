import type { FastifyInstance } from "fastify";

import type { OrchestratorServices } from "../services.js";

export async function registerApprovalRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/approvals", async () => ({ data: await services.repository.listApprovals() }));
}

