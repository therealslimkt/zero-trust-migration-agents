import type { FastifyInstance } from "fastify";

import { getSystemStatus } from "../../system/health.js";
import type { OrchestratorServices } from "../services.js";

export async function registerSystemRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/system", async () => {
    const [tasks, approvals] = await Promise.all([
      services.repository.listTasks(),
      services.repository.listApprovals(),
    ]);
    const providerHealth = Object.fromEntries(
      [...services.providerCache.values()].map((provider) => [provider.providerId, provider.health]),
    );
    const status = getSystemStatus({
      activeWorkers: tasks.filter((task) => task.status === "running").length,
      queuedTasks: tasks.filter((task) => task.status === "queued").length,
      pendingApprovals: approvals.filter((approval) => approval.status === "pending").length,
    }, {
      postgres: "healthy",
      ...providerHealth,
    });
    return { data: status };
  });
}

