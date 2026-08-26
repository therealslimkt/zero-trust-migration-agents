import type { FastifyInstance } from "fastify";

import type { ArtifactRecord } from "../../../control/contracts.generated.js";
import type { OrchestratorServices } from "../services.js";

export async function registerArtifactRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/artifacts", async () => ({ data: await services.repository.listArtifacts() }));

  app.post<{ Body: ArtifactRecord }>("/api/v1/artifacts", {
    schema: {
      body: {
        type: "object",
        additionalProperties: false,
        required: ["schemaVersion", "artifactId", "taskId", "createdBy", "kind", "path", "validationStatus", "createdAt"],
        properties: {
          schemaVersion: { type: "string" },
          artifactId: { type: "string", minLength: 1 },
          taskId: { type: "string", minLength: 1 },
          createdBy: { type: "string", minLength: 1 },
          kind: { type: "string", minLength: 1 },
          path: { type: "string", minLength: 1 },
          mediaType: { type: ["string", "null"] },
          validationStatus: { enum: ["pending", "valid", "invalid", "not_applicable"] },
          reviewerAgentId: { type: ["string", "null"] },
          mergeReadiness: { enum: ["not_ready", "review", "ready", "rejected", null] },
          createdAt: { type: "string", format: "date-time" },
        },
      },
    },
  }, async (request, reply) => {
    await services.repository.saveArtifact(request.body);
    return reply.code(201).send({ data: request.body });
  });
}
