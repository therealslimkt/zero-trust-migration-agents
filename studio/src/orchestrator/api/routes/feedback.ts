import type { FastifyInstance } from "fastify";

import type { FeedbackRecord } from "../../../control/contracts.generated.js";
import type { OrchestratorServices } from "../services.js";

export async function registerFeedbackRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/feedback", async () => ({
    data: await services.repository.listFeedback(),
    candidates: await services.repository.listMemoryCandidates(),
  }));

  app.post<{ Body: FeedbackRecord }>("/api/v1/feedback", {
    schema: {
      body: {
        type: "object",
        additionalProperties: false,
        required: ["schemaVersion", "feedbackId", "taskId", "subjectAgentId", "source", "sentiment", "summary", "promotionStatus", "createdAt"],
        properties: {
          schemaVersion: { type: "string" },
          feedbackId: { type: "string" },
          taskId: { type: "string" },
          subjectAgentId: { type: "string" },
          source: { type: "string" },
          sentiment: { type: "string" },
          score: { type: ["number", "null"], minimum: 0, maximum: 1 },
          summary: { type: "string", minLength: 1 },
          evidenceRefs: { type: "array", items: { type: "string" } },
          promotionStatus: { type: "string" },
          createdAt: { type: "string", format: "date-time" },
        },
      },
    },
  }, async (request, reply) => {
    await services.repository.saveFeedback(request.body);
    return reply.code(201).send({ data: request.body });
  });
}

