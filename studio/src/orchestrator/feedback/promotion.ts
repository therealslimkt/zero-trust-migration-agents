import { randomUUID } from "node:crypto";

import type { FeedbackRecord, MemoryCandidate } from "../../control/contracts.generated.js";

export interface CandidatePolicy {
  minimumEvidenceCount: number;
  minimumAverageScore: number;
}

export function proposeMemoryCandidate(
  agentId: MemoryCandidate["agentId"],
  lesson: string,
  feedback: FeedbackRecord[],
  policy: CandidatePolicy = { minimumEvidenceCount: 2, minimumAverageScore: 0.75 },
): MemoryCandidate | null {
  const relevant = feedback.filter((record) => record.subjectAgentId === agentId && record.score != null);
  if (relevant.length < policy.minimumEvidenceCount) return null;

  const confidence = relevant.reduce((sum, record) => sum + (record.score ?? 0), 0) / relevant.length;
  if (confidence < policy.minimumAverageScore) return null;

  return {
    schemaVersion: "0.1.0",
    candidateId: `memory_candidate_${randomUUID()}`,
    agentId,
    lesson,
    evidenceFeedbackIds: relevant.map((record) => record.feedbackId),
    confidence,
    status: "proposed",
    requiresHumanApproval: true,
    createdAt: new Date().toISOString(),
  };
}
