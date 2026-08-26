import type { FastifyInstance } from "fastify";

import { discoverProviders } from "../../providers/discovery.js";
import type { OrchestratorServices } from "../services.js";

export async function registerProviderRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/providers", async () => {
    const statuses = await discoverProviders(services.providers);
    await Promise.all(statuses.map((status) => services.repository.saveProviderStatus(status)));
    statuses.forEach((status) => services.providerCache.set(status.providerId, status));
    return { data: statuses };
  });
}

