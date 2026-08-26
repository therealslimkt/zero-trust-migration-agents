import type { FastifyInstance } from "fastify";

import type { A2AEvent } from "../../../control/contracts.generated.js";
import type { OrchestratorServices } from "../services.js";

export async function registerEventRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get<{ Querystring: { limit?: string } }>("/api/v1/events", async (request) => {
    const parsedLimit = Number.parseInt(request.query.limit ?? "200", 10);
    return { data: await services.repository.recentEvents(Number.isFinite(parsedLimit) ? parsedLimit : 200) };
  });

  app.post<{ Body: A2AEvent }>("/api/v1/events", {
    schema: {
      body: {
        type: "object",
        additionalProperties: false,
        required: ["schemaVersion", "eventId", "traceId", "taskId", "from", "to", "type", "timestamp", "summary", "contextRefs", "artifactRefs", "status", "requiresHumanApproval"],
        properties: {
          schemaVersion: { type: "string" },
          eventId: { type: "string", minLength: 1 },
          traceId: { type: "string", minLength: 1 },
          parentEventId: { type: ["string", "null"] },
          taskId: { type: "string", minLength: 1 },
          from: { type: "string", minLength: 1 },
          to: { type: "string", minLength: 1 },
          type: { type: "string", minLength: 1 },
          timestamp: { type: "string", format: "date-time" },
          summary: { type: "string", minLength: 1 },
          contextRefs: { type: "array", items: { type: "string" } },
          artifactRefs: { type: "array", items: { type: "string" } },
          status: { enum: ["proposed", "queued", "running", "blocked", "review", "ready", "complete", "failed", "cancelled"] },
          requiresHumanApproval: { type: "boolean" },
          payload: {},
        },
      },
    },
  }, async (request, reply) => {
    await services.events.publish(request.body);
    return reply.code(201).send({ data: request.body });
  });
}
