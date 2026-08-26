// Generated control-contract snapshot.
// Canonical sources: plan/agents/schemas/*.schema.json
// Regenerate after dependency installation; do not hand-edit downstream copies.

export const CONTROL_SCHEMA_VERSION = "0.1.0" as const;

export type AgentId =
  | "mission_control"
  | "architect"
  | "compiler"
  | "grammar_police"
  | "stage_manager"
  | "universal_translator"
  | "scout"
  | "front_of_house"
  | "fixer"
  | "breaker"
  | "gatekeeper"
  | "maestro"
  | "bette_davis_eyes"
  | "gifted_animator"
  | "piano_man"
  | "critic_that_counts"
  | "easter_bunny"
  | "golden_goose"
  | "pop_lock_and_drop_it";

export type ProviderId = "codex" | "antigravity" | "claude";

export type TaskStatus =
  | "proposed"
  | "queued"
  | "running"
  | "blocked"
  | "review"
  | "ready"
  | "complete"
  | "failed"
  | "cancelled";

export type HealthStatus = "healthy" | "degraded" | "unavailable" | "unknown";

export interface AgentSummary {
  schemaVersion: string;
  id: AgentId;
  displayName: string;
  kind: "build" | "product";
  status: "idle" | "queued" | "running" | "blocked" | "review" | "offline" | "error";
  modelPolicy: string;
  activeProvider?: ProviderId | null;
  activeModel?: string | null;
  currentTaskId?: string | null;
  workspace?: string | null;
  contextScope?: string[];
}

export interface ProviderStatus {
  schemaVersion: string;
  providerId: ProviderId;
  displayName: string;
  discovery: "available" | "not_on_path" | "not_installed" | "broken";
  executablePath?: string | null;
  version?: string | null;
  authentication: "authenticated" | "required" | "not_applicable" | "unknown";
  health: HealthStatus;
  currentModel?: string | null;
  currentAgentId?: AgentId | null;
  currentTaskId?: string | null;
  lastInvocationAt?: string | null;
  error?: string | null;
  updatedAt: string;
}

export interface AgentRouteTarget {
  provider: ProviderId;
  model: string;
  reasoning?: string | null;
}

export interface AgentRoute {
  schemaVersion: string;
  agentId: AgentId;
  modelPolicy: string;
  primary: AgentRouteTarget;
  fallbacks: AgentRouteTarget[];
  cloudAllowed?: boolean;
}

export interface TaskEnvelope {
  schemaVersion: string;
  taskId: string;
  traceId: string;
  title: string;
  objective: string;
  ownerAgentId: AgentId;
  reviewerAgentId?: AgentId | null;
  status: TaskStatus;
  branch?: string | null;
  workspace?: string | null;
  readAllowlist: string[];
  readDenylist: string[];
  writeAllowlist: string[];
  contextRefs?: string[];
  networkPolicy: "deny" | "allowlist";
  allowedCommands?: string[];
  acceptanceCriteria: string[];
  stopConditions?: string[];
  createdAt: string;
}

export interface ValidationCheck {
  name: string;
  status: "passed" | "failed" | "skipped";
  detail?: string | null;
}

export interface ResultEnvelope {
  schemaVersion: string;
  taskId: string;
  traceId: string;
  agentId: AgentId;
  status: "ready" | "complete" | "failed" | "blocked" | "cancelled";
  summary: string;
  artifactIds: string[];
  validation: ValidationCheck[];
  error?: string | null;
  completedAt: string;
}

export interface ContextRequest {
  schemaVersion: string;
  requestId: string;
  taskId: string;
  agentId: AgentId;
  paths: string[];
  reason: string;
  status: "pending" | "granted" | "denied" | "expired";
  createdAt: string;
}

export interface ContextGrant {
  schemaVersion: string;
  grantId: string;
  requestId: string;
  taskId: string;
  agentId: AgentId;
  paths: string[];
  grantedBy: string;
  expiresAt?: string | null;
  createdAt: string;
}

export interface ApprovalRequest {
  schemaVersion: string;
  approvalId: string;
  taskId: string;
  requestingAgentId: AgentId;
  action: string;
  risk: "low" | "medium" | "high" | "critical";
  reason: string;
  status: "pending" | "granted" | "denied" | "cancelled";
  decidedBy?: string | null;
  decidedAt?: string | null;
  createdAt: string;
}

export interface A2AEvent {
  schemaVersion: string;
  eventId: string;
  traceId: string;
  parentEventId?: string | null;
  taskId: string;
  from: AgentId;
  to: AgentId | "broadcast";
  type: string;
  timestamp: string;
  summary: string;
  contextRefs: string[];
  artifactRefs: string[];
  status: TaskStatus;
  requiresHumanApproval: boolean;
  payload?: unknown;
}

export interface ArtifactRecord {
  schemaVersion: string;
  artifactId: string;
  taskId: string;
  createdBy: AgentId;
  kind: string;
  path: string;
  mediaType?: string | null;
  validationStatus: "pending" | "valid" | "invalid" | "not_applicable";
  reviewerAgentId?: AgentId | null;
  mergeReadiness?: "not_ready" | "review" | "ready" | "rejected";
  createdAt: string;
}

export interface SystemStatus {
  schemaVersion: string;
  status: Exclude<HealthStatus, "unknown">;
  activeWorkers: number;
  queuedTasks: number;
  pendingApprovals: number;
  cpuPercent: number;
  memoryUsedBytes: number;
  memoryTotalBytes: number;
  services: Record<string, HealthStatus>;
  updatedAt: string;
}

export interface FeedbackRecord {
  schemaVersion: string;
  feedbackId: string;
  taskId: string;
  subjectAgentId: AgentId;
  source: "founder" | "reviewer" | "deterministic_eval" | "task_outcome" | "user";
  sentiment: "positive" | "negative" | "mixed" | "neutral";
  score?: number | null;
  summary: string;
  evidenceRefs?: string[];
  promotionStatus: "raw" | "candidate" | "approved" | "rejected" | "promoted";
  createdAt: string;
}

export interface EvalRun {
  schemaVersion: string;
  evalRunId: string;
  taskId: string;
  agentId: AgentId;
  rubricId: string;
  status: "running" | "passed" | "failed" | "error";
  score?: number | null;
  checks: ValidationCheck[];
  startedAt: string;
  completedAt?: string | null;
}

export interface MemoryCandidate {
  schemaVersion: string;
  candidateId: string;
  agentId: AgentId;
  lesson: string;
  evidenceFeedbackIds: string[];
  confidence: number;
  status: "proposed" | "approved" | "rejected" | "promoted";
  requiresHumanApproval: true;
  createdAt: string;
}

export interface RoutingOutcome {
  schemaVersion: string;
  routingOutcomeId: string;
  taskId: string;
  agentId: AgentId;
  providerId: ProviderId;
  model: string;
  resultStatus: "complete" | "failed" | "blocked" | "cancelled";
  qualityScore?: number | null;
  durationMs: number;
  estimatedCostUsd?: number | null;
  createdAt: string;
}

