import type { AgentSummary, TaskEnvelope, TaskStatus } from "../../../../control/contracts.generated.js";

export type AgentActivityState = "idle" | "queued" | "running" | "review" | "complete" | "blocked" | "error";

export interface AgentActivity {
  state: AgentActivityState;
  label: string;
  task: TaskEnvelope | null;
}

const activeStatuses: TaskStatus[] = ["running", "review", "blocked", "queued", "ready"];

export function deriveAgentActivity(agent: AgentSummary, tasks: readonly TaskEnvelope[]): AgentActivity {
  const owned = tasks
    .filter((task) => task.ownerAgentId === agent.id)
    .sort((first, second) => Date.parse(second.createdAt) - Date.parse(first.createdAt));
  const active = activeStatuses
    .map((status) => owned.find((task) => task.status === status))
    .find((task) => task !== undefined);

  if (active) {
    const state = active.status === "ready" ? "review" : active.status as AgentActivityState;
    return { state, label: `${active.status}: ${active.title}`, task: active };
  }
  if (agent.status === "error") return { state: "error", label: "Needs operator attention", task: owned[0] ?? null };
  if (agent.status === "blocked") return { state: "blocked", label: "Blocked and awaiting help", task: owned[0] ?? null };
  return { state: "idle", label: owned[0] ? `Awaiting next cue · last ${owned[0].status}` : "Awaiting next cue", task: owned[0] ?? null };
}
