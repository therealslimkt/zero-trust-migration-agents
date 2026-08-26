import Fastify, { type FastifyError, type FastifyInstance } from "fastify";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";

import type { OrchestratorServices } from "./services.js";
import { registerAgentRoutes } from "./routes/agents.js";
import { registerApprovalRoutes } from "./routes/approvals.js";
import { registerArtifactRoutes } from "./routes/artifacts.js";
import { registerEventRoutes } from "./routes/events.js";
import { registerFeedbackRoutes } from "./routes/feedback.js";
import { registerProviderRoutes } from "./routes/providers.js";
import { registerSystemRoutes } from "./routes/system.js";
import { registerTaskRoutes } from "./routes/tasks.js";
import { registerEventStream } from "./streams/events.js";

export async function createApiServer(services: OrchestratorServices): Promise<FastifyInstance> {
  const app = Fastify({
    logger: true,
    requestIdHeader: "x-request-id",
  });

  await app.register(swagger, {
    openapi: {
      info: { title: "Skin Mission Control API", version: "0.1.0" },
      servers: [{ url: "http://127.0.0.1:4317", description: "Local Mission Control" }],
    },
  });
  await app.register(swaggerUi, { routePrefix: "/docs" });

  app.setErrorHandler((error: FastifyError, request, reply) => {
    request.log.error({ error, requestId: request.id }, "request failed");
    void reply.code(error.statusCode ?? 500).send({
      error: {
        code: error.code ?? "INTERNAL_ERROR",
        message: error.statusCode && error.statusCode < 500 ? error.message : "Internal server error",
        requestId: request.id,
      },
    });
  });

  app.get("/healthz", async () => ({ status: "ok" }));
  await registerAgentRoutes(app, services);
  await registerProviderRoutes(app, services);
  await registerTaskRoutes(app, services);
  await registerApprovalRoutes(app, services);
  await registerArtifactRoutes(app, services);
  await registerEventRoutes(app, services);
  await registerFeedbackRoutes(app, services);
  await registerSystemRoutes(app, services);
  await registerEventStream(app, services);

  return app;
}
