import { randomUUID } from "node:crypto";

import type { FastifyInstance } from "fastify";

import type { A2AEvent, TaskEnvelope, TaskStatus } from "../../../control/contracts.generated.js";
import type { OrchestratorServices } from "../services.js";

const taskStatuses: TaskStatus[] = ["proposed", "queued", "running", "blocked", "review", "ready", "complete", "failed", "cancelled"];

function taskEvent(task: TaskEnvelope, type: string, summary: string): A2AEvent {
  return {
    schemaVersion: task.schemaVersion,
    eventId: randomUUID(),
    traceId: task.traceId,
    taskId: task.taskId,
    from: "mission_control",
    to: task.ownerAgentId,
    type,
    timestamp: new Date().toISOString(),
    summary,
    contextRefs: task.contextRefs ?? [],
    artifactRefs: [],
    status: task.status,
    requiresHumanApproval: false,
  };
}

export async function registerTaskRoutes(app: FastifyInstance, services: OrchestratorServices): Promise<void> {
  app.get("/api/v1/tasks", async () => ({ data: await services.repository.listTasks() }));

  app.post<{ Body: TaskEnvelope }>("/api/v1/tasks", {
    schema: {
      body: {
        type: "object",
        additionalProperties: false,
        required: ["schemaVersion", "taskId", "traceId", "title", "objective", "ownerAgentId", "status", "readAllowlist", "readDenylist", "writeAllowlist", "networkPolicy", "acceptanceCriteria", "createdAt"],
        properties: {
          schemaVersion: { type: "string" },
          taskId: { type: "string", minLength: 1 },
          traceId: { type: "string", minLength: 1 },
          title: { type: "string", minLength: 1 },
          objective: { type: "string", minLength: 1 },
          ownerAgentId: { type: "string", minLength: 1 },
          reviewerAgentId: { type: ["string", "null"] },
          status: { enum: taskStatuses },
          branch: { type: ["string", "null"] },
          workspace: { type: ["string", "null"] },
          readAllowlist: { type: "array", items: { type: "string" } },
          readDenylist: { type: "array", items: { type: "string" } },
          writeAllowlist: { type: "array", items: { type: "string" } },
          contextRefs: { type: "array", items: { type: "string" } },
          networkPolicy: { enum: ["deny", "allowlist"] },
          allowedCommands: { type: "array", items: { type: "string" } },
          acceptanceCriteria: { type: "array", minItems: 1, items: { type: "string" } },
          stopConditions: { type: "array", items: { type: "string" } },
          createdAt: { type: "string", format: "date-time" },
        },
      },
    },
  }, async (request, reply) => {
    await services.repository.saveTask(request.body);
    await services.events.publish(taskEvent(request.body, "task.created", `Queued: ${request.body.title}`));
    return reply.code(201).send({ data: request.body });
  });

  app.patch<{ Params: { taskId: string }; Body: { status: TaskStatus; summary: string } }>("/api/v1/tasks/:taskId", {
    schema: {
      params: {
        type: "object",
        additionalProperties: false,
        required: ["taskId"],
        properties: { taskId: { type: "string", minLength: 1 } },
      },
      body: {
        type: "object",
        additionalProperties: false,
        required: ["status", "summary"],
        properties: {
          status: { enum: taskStatuses },
          summary: { type: "string", minLength: 1 },
        },
      },
    },
  }, async (request, reply) => {
    const current = await services.repository.getTask(request.params.taskId);
    if (!current) {
      return reply.code(404).send({
        error: { code: "TASK_NOT_FOUND", message: "Task not found", requestId: request.id },
      });
    }
    const updated = { ...current, status: request.body.status };
    await services.repository.saveTask(updated);
    await services.events.publish(taskEvent(updated, `task.${request.body.status}`, request.body.summary));
    return { data: updated };
  });
}
