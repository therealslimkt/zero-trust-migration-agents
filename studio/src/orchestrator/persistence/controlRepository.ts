import type {
  A2AEvent,
  ApprovalRequest,
  ArtifactRecord,
  FeedbackRecord,
  MemoryCandidate,
  ProviderStatus,
  TaskEnvelope,
} from "../../control/contracts.generated.js";
import type { DatabasePool } from "./postgres.js";

export class ControlRepository {
  constructor(private readonly pool: DatabasePool) {}

  async saveEvent(event: A2AEvent): Promise<void> {
    await this.pool.query(
      `INSERT INTO events(event_id, trace_id, task_id, event_type, event, created_at)
       VALUES ($1, $2, $3, $4, $5, $6)
       ON CONFLICT (event_id) DO NOTHING`,
      [event.eventId, event.traceId, event.taskId, event.type, event, event.timestamp],
    );
  }

  async recentEvents(limit = 200): Promise<A2AEvent[]> {
    const result = await this.pool.query<{ event: A2AEvent }>(
      "SELECT event FROM events ORDER BY created_at DESC LIMIT $1",
      [Math.min(Math.max(limit, 1), 1_000)],
    );
    return result.rows.map((row) => row.event).reverse();
  }

  async saveProviderStatus(status: ProviderStatus): Promise<void> {
    await this.pool.query(
      `INSERT INTO provider_status(provider_id, status, updated_at)
       VALUES ($1, $2, $3)
       ON CONFLICT (provider_id) DO UPDATE SET status = EXCLUDED.status, updated_at = EXCLUDED.updated_at`,
      [status.providerId, status, status.updatedAt],
    );
  }

  async saveTask(task: TaskEnvelope): Promise<void> {
    await this.pool.query(
      `INSERT INTO tasks(task_id, trace_id, owner_agent_id, reviewer_agent_id, status, envelope, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7)
       ON CONFLICT (task_id) DO UPDATE SET status = EXCLUDED.status, envelope = EXCLUDED.envelope, updated_at = now()`,
      [task.taskId, task.traceId, task.ownerAgentId, task.reviewerAgentId ?? null, task.status, task, task.createdAt],
    );
  }

  async listTasks(): Promise<TaskEnvelope[]> {
    const result = await this.pool.query<{ envelope: TaskEnvelope }>("SELECT envelope FROM tasks ORDER BY updated_at DESC");
    return result.rows.map((row) => row.envelope);
  }

  async getTask(taskId: string): Promise<TaskEnvelope | null> {
    const result = await this.pool.query<{ envelope: TaskEnvelope }>(
      "SELECT envelope FROM tasks WHERE task_id = $1",
      [taskId],
    );
    return result.rows[0]?.envelope ?? null;
  }

  async listApprovals(): Promise<ApprovalRequest[]> {
    const result = await this.pool.query<{ request: ApprovalRequest }>("SELECT request FROM approvals ORDER BY updated_at DESC");
    return result.rows.map((row) => row.request);
  }

  async listArtifacts(): Promise<ArtifactRecord[]> {
    const result = await this.pool.query<{ record: ArtifactRecord }>("SELECT record FROM artifacts ORDER BY created_at DESC");
    return result.rows.map((row) => row.record);
  }

  async saveArtifact(artifact: ArtifactRecord): Promise<void> {
    await this.pool.query(
      `INSERT INTO artifacts(artifact_id, task_id, created_by, record, created_at)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (artifact_id) DO UPDATE SET record = EXCLUDED.record`,
      [artifact.artifactId, artifact.taskId, artifact.createdBy, artifact, artifact.createdAt],
    );
  }

  async saveFeedback(feedback: FeedbackRecord): Promise<void> {
    await this.pool.query(
      `INSERT INTO feedback(feedback_id, task_id, subject_agent_id, source, sentiment, score, summary, evidence_refs, promotion_status, created_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
      [feedback.feedbackId, feedback.taskId, feedback.subjectAgentId, feedback.source, feedback.sentiment, feedback.score ?? null, feedback.summary, feedback.evidenceRefs ?? [], feedback.promotionStatus, feedback.createdAt],
    );
  }

  async listFeedback(): Promise<FeedbackRecord[]> {
    const result = await this.pool.query<FeedbackRecord>(
      `SELECT feedback_id AS "feedbackId", task_id AS "taskId", subject_agent_id AS "subjectAgentId",
              source, sentiment, score, summary, evidence_refs AS "evidenceRefs",
              promotion_status AS "promotionStatus", created_at AS "createdAt", '0.1.0' AS "schemaVersion"
       FROM feedback ORDER BY created_at DESC`,
    );
    return result.rows.map((row) => ({ ...row, createdAt: new Date(row.createdAt).toISOString() }));
  }

  async listMemoryCandidates(): Promise<MemoryCandidate[]> {
    const result = await this.pool.query<MemoryCandidate>(
      `SELECT candidate_id AS "candidateId", agent_id AS "agentId", lesson,
              evidence_feedback_ids AS "evidenceFeedbackIds", confidence, status,
              true AS "requiresHumanApproval", created_at AS "createdAt", '0.1.0' AS "schemaVersion"
       FROM memory_candidates ORDER BY created_at DESC`,
    );
    return result.rows.map((row) => ({ ...row, createdAt: new Date(row.createdAt).toISOString() }));
  }
}
