import { randomUUID } from "node:crypto";
import { access } from "node:fs/promises";
import { resolve } from "node:path";

import type { A2AEvent, ArtifactRecord, TaskEnvelope, TaskStatus } from "../../control/contracts.generated.js";
import { loadRuntimeConfig } from "../config/runtime.js";
import { ContextBroker } from "../context/broker.js";

const apiRoot = process.env.SKIN_API_ROOT ?? "http://127.0.0.1:4317/api/v1";
const traceId = "v2-bootstrap-integration-demo";

async function post<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const response = await fetch(`${apiRoot}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`);
  return response.json() as Promise<T>;
}

function event(task: TaskEnvelope, type: string, summary: string, payload?: unknown): A2AEvent {
  return {
    schemaVersion: "0.1.0",
    eventId: randomUUID(),
    traceId,
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
    ...(payload === undefined ? {} : { payload }),
  };
}

async function setStatus(taskId: string, status: TaskStatus, summary: string): Promise<void> {
  await post(`/tasks/${taskId}`, { status, summary }, "PATCH");
}

async function registerArtifact(record: ArtifactRecord): Promise<void> {
  await access(resolve(loadRuntimeConfig().repositoryRoot, record.path));
  await post("/artifacts", record);
}

async function main(): Promise<void> {
  const config = loadRuntimeConfig();
  const createdAt = new Date().toISOString();
  const codexTask: TaskEnvelope = {
    schemaVersion: "0.1.0",
    taskId: "v2-demo-codex-implementation",
    traceId,
    title: "Codex: bounded task summary implementation",
    objective: "Implement a pure formatter using only the task capsule contract.",
    ownerAgentId: "fixer",
    reviewerAgentId: "gatekeeper",
    status: "queued",
    branch: "mission_control/v2_bootstrap",
    workspace: ".task-context/v2-demo/codex-implementation",
    readAllowlist: [".task-context/v2-demo/codex-implementation/**"],
    readDenylist: ["plan/agents/**/context/**", "research/audio/**", ".env*"],
    writeAllowlist: [".task-context/v2-demo/codex-implementation/taskSummary.ts", ".task-context/v2-demo/codex-implementation/implementation-notes.md"],
    contextRefs: [".task-context/v2-demo/codex-implementation/TASK.md", ".task-context/v2-demo/codex-implementation/CONTRACT.ts"],
    networkPolicy: "allowlist",
    allowedCommands: [],
    acceptanceCriteria: ["Exact summary format", "Whitespace normalized", "Pure named export"],
    stopConditions: ["Any required input is outside the capsule"],
    createdAt,
  };
  const reviewTask: TaskEnvelope = {
    schemaVersion: "0.1.0",
    taskId: "v2-demo-antigravity-review",
    traceId,
    title: "Antigravity: independent capsule review",
    objective: "Review the bounded Codex artifact against the supplied acceptance criteria.",
    ownerAgentId: "gatekeeper",
    reviewerAgentId: "mission_control",
    status: "queued",
    branch: "mission_control/v2_bootstrap",
    workspace: ".task-context/v2-demo/antigravity-review",
    readAllowlist: [".task-context/v2-demo/antigravity-review/**"],
    readDenylist: ["plan/agents/**/context/**", "research/audio/**", ".env*"],
    writeAllowlist: [".task-context/v2-demo/antigravity-review/review.md"],
    contextRefs: [".task-context/v2-demo/antigravity-review/TASK.md", ".task-context/v2-demo/antigravity-review/taskSummary.ts"],
    networkPolicy: "allowlist",
    allowedCommands: [],
    acceptanceCriteria: ["Checks every acceptance criterion", "Reports evidence", "Returns PASS or FAIL"],
    stopConditions: ["Any required input is outside the capsule"],
    createdAt,
  };

  await post("/tasks", codexTask);
  const broker = await ContextBroker.create(config.repositoryRoot);
  const requestedPath = "plan/agents/product_agents/piano_man/context/private-note.md";
  const denial = await broker.authorizeRead(requestedPath, {
    readAllowlist: ["plan/agents/product_agents/piano_man/context/**"],
    readDenylist: [],
    writeAllowlist: [],
  });
  if (denial.allowed || denial.reason !== "protected_context_requires_grant") {
    throw new Error(`Expected protected-context denial, received ${JSON.stringify(denial)}`);
  }
  await post("/events", event(codexTask, "context.denied", "Context Broker denied a protected path before content access.", {
    requestedPath,
    reason: denial.reason,
    contentRead: false,
  }));
  await setStatus(codexTask.taskId, "running", "Codex ran inside the implementation capsule.");
  await registerArtifact({
    schemaVersion: "0.1.0",
    artifactId: "v2-demo-codex-task-summary",
    taskId: codexTask.taskId,
    createdBy: "fixer",
    kind: "typescript-source",
    path: ".task-context/v2-demo/codex-implementation/taskSummary.ts",
    mediaType: "text/typescript",
    validationStatus: "valid",
    reviewerAgentId: "gatekeeper",
    mergeReadiness: "review",
    createdAt: new Date().toISOString(),
  });
  await setStatus(codexTask.taskId, "complete", "Codex implementation artifact recorded and ready for independent review.");

  await post("/tasks", reviewTask);
  await setStatus(reviewTask.taskId, "running", "Antigravity reviewed only the copied capsule artifact and criteria.");
  await registerArtifact({
    schemaVersion: "0.1.0",
    artifactId: "v2-demo-antigravity-review",
    taskId: reviewTask.taskId,
    createdBy: "gatekeeper",
    kind: "review",
    path: ".task-context/v2-demo/antigravity-review/review.md",
    mediaType: "text/markdown",
    validationStatus: "valid",
    reviewerAgentId: "mission_control",
    mergeReadiness: "ready",
    createdAt: new Date().toISOString(),
  });
  await setStatus(reviewTask.taskId, "complete", "Antigravity independent review passed and was recorded.");

  console.log("V2 integration demo recorded: two tasks, two artifacts, and one protected-context denial.");
}

await main();
