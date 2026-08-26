import { useQuery } from "@tanstack/react-query";

import type {
  A2AEvent,
  AgentSummary,
  ApprovalRequest,
  ArtifactRecord,
  FeedbackRecord,
  MemoryCandidate,
  ProviderStatus,
  SystemStatus,
  TaskEnvelope,
} from "../../../control/contracts.generated.js";
import { api, type ApiEnvelope } from "./client.js";

export const queryKeys = {
  agents: ["agents"] as const,
  providers: ["providers"] as const,
  tasks: ["tasks"] as const,
  events: ["events"] as const,
  approvals: ["approvals"] as const,
  artifacts: ["artifacts"] as const,
  feedback: ["feedback"] as const,
  system: ["system"] as const,
};

export const useAgents = () => useQuery({ queryKey: queryKeys.agents, queryFn: async () => (await api.get<ApiEnvelope<AgentSummary[]>>("/api/v1/agents")).data });
export const useProviders = () => useQuery({ queryKey: queryKeys.providers, queryFn: async () => (await api.get<ApiEnvelope<ProviderStatus[]>>("/api/v1/providers")).data });
export const useTasks = () => useQuery({ queryKey: queryKeys.tasks, queryFn: async () => (await api.get<ApiEnvelope<TaskEnvelope[]>>("/api/v1/tasks")).data });
export const useEvents = () => useQuery({ queryKey: queryKeys.events, queryFn: async () => (await api.get<ApiEnvelope<A2AEvent[]>>("/api/v1/events?limit=250")).data });
export const useApprovals = () => useQuery({ queryKey: queryKeys.approvals, queryFn: async () => (await api.get<ApiEnvelope<ApprovalRequest[]>>("/api/v1/approvals")).data });
export const useArtifacts = () => useQuery({ queryKey: queryKeys.artifacts, queryFn: async () => (await api.get<ApiEnvelope<ArtifactRecord[]>>("/api/v1/artifacts")).data });
export const useSystemStatus = () => useQuery({ queryKey: queryKeys.system, queryFn: async () => (await api.get<ApiEnvelope<SystemStatus>>("/api/v1/system")).data, refetchInterval: 5_000 });
export const useFeedback = () => useQuery({
  queryKey: queryKeys.feedback,
  queryFn: () => api.get<ApiEnvelope<FeedbackRecord[]> & { candidates: MemoryCandidate[] }>("/api/v1/feedback"),
});

