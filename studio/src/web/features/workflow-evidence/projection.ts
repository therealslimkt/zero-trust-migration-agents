/**
 * A narrow, persisted-only execution projection.  This deliberately does not
 * reuse the narrative event stream: every entry must be supplied by the
 * server, and is discarded if its provenance cannot be established.
 */
export type WorkflowNodeState = 'queued' | 'running' | 'interrupted' | 'succeeded' | 'failed' | 'cancelled'

interface PersistedEntry {
  readonly sequence: number
  readonly eventId: string
  readonly persisted: true
  readonly state: WorkflowNodeState
  readonly checkpointRef?: string
  readonly evidenceDigest: string
}

export interface ModelCallEvidence extends PersistedEntry {
  readonly kind: 'node'
  readonly workClass: 'model_call'
  readonly modelCall: true
  readonly nodePath: string
  readonly agentId: string
}

export interface DeterministicEvidence extends PersistedEntry {
  readonly kind: 'node'
  readonly workClass: 'deterministic_function' | 'control_flow'
  readonly modelCall: false
  readonly nodePath: string
  readonly deterministicComponentId: string
}

export interface ApprovalInterruptEvidence extends PersistedEntry {
  readonly kind: 'approval_interrupt'
  readonly approvalKind: 'simulation_approval' | 'production_approval'
  readonly interruptId: string
  readonly resumeChannel: 'approval_endpoint'
  readonly subjectDigest: string
  readonly decision: 'pending' | 'approved' | 'rejected'
  readonly approvalId?: string
}

export type WorkflowEvidenceEntry = ModelCallEvidence | DeterministicEvidence | ApprovalInterruptEvidence

export type WorkflowEvidenceProjection =
  | { readonly status: 'unavailable' }
  | { readonly status: 'ready'; readonly replayCursor: string; readonly complete: boolean; readonly entries: readonly WorkflowEvidenceEntry[] }

export const WORKFLOW_EVIDENCE_UNAVAILABLE: WorkflowEvidenceProjection = { status: 'unavailable' }

const DIGEST = /^sha256:[a-f0-9]{64}$/
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:/-]{2,255}$/
const NODE_STATES = new Set<WorkflowNodeState>(['queued', 'running', 'interrupted', 'succeeded', 'failed', 'cancelled'])
const DECISIONS = new Set<ApprovalInterruptEvidence['decision']>(['pending', 'approved', 'rejected'])

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined
}

function identifier(value: unknown): value is string {
  return typeof value === 'string' && IDENTIFIER.test(value)
}

function digest(value: unknown): value is string {
  return typeof value === 'string' && DIGEST.test(value)
}

function persistedBase(value: Record<string, unknown>): value is Record<string, unknown> & PersistedEntry {
  return Number.isSafeInteger(value.sequence) && (value.sequence as number) >= 1 &&
    identifier(value.eventId) && value.persisted === true && typeof value.state === 'string' &&
    NODE_STATES.has(value.state as WorkflowNodeState) && digest(value.evidenceDigest) &&
    (value.checkpointRef === undefined || identifier(value.checkpointRef))
}

function entry(value: unknown): WorkflowEvidenceEntry | undefined {
  const candidate = object(value)
  if (!candidate || !persistedBase(candidate)) return undefined
  if (candidate.kind === 'node') {
    if (!identifier(candidate.nodePath) || typeof candidate.modelCall !== 'boolean') return undefined
    if (candidate.modelCall === true && candidate.workClass === 'model_call' && identifier(candidate.agentId) && candidate.deterministicComponentId === undefined) {
      return candidate as unknown as ModelCallEvidence
    }
    if (candidate.modelCall === false && (candidate.workClass === 'deterministic_function' || candidate.workClass === 'control_flow') && identifier(candidate.deterministicComponentId) && candidate.agentId === undefined) {
      return candidate as unknown as DeterministicEvidence
    }
    return undefined
  }
  if (candidate.kind !== 'approval_interrupt' ||
    (candidate.approvalKind !== 'simulation_approval' && candidate.approvalKind !== 'production_approval') ||
    !identifier(candidate.interruptId) || candidate.resumeChannel !== 'approval_endpoint' || !digest(candidate.subjectDigest) ||
    typeof candidate.decision !== 'string' || !DECISIONS.has(candidate.decision as ApprovalInterruptEvidence['decision'])) return undefined
  if ((candidate.decision === 'pending' && candidate.approvalId !== undefined) ||
    (candidate.decision !== 'pending' && !identifier(candidate.approvalId))) return undefined
  return candidate as unknown as ApprovalInterruptEvidence
}

/**
 * Decodes only an exact, server-provided persisted projection. A malformed
 * response is intentionally indistinguishable from an absent optional
 * endpoint so consumers cannot turn malformed data into execution claims.
 */
export function parseWorkflowEvidenceProjection(value: unknown): WorkflowEvidenceProjection {
  const candidate = object(value)
  if (!candidate || candidate.status !== 'ready' || !identifier(candidate.replayCursor) || typeof candidate.complete !== 'boolean' || !Array.isArray(candidate.entries) || candidate.entries.length === 0) return WORKFLOW_EVIDENCE_UNAVAILABLE
  const entries: WorkflowEvidenceEntry[] = []
  const eventIds = new Set<string>()
  let expectedSequence = 1
  for (const rawEntry of candidate.entries) {
    const parsed = entry(rawEntry)
    if (!parsed || parsed.sequence !== expectedSequence || eventIds.has(parsed.eventId)) return WORKFLOW_EVIDENCE_UNAVAILABLE
    entries.push(parsed)
    eventIds.add(parsed.eventId)
    expectedSequence += 1
  }
  return { status: 'ready', replayCursor: candidate.replayCursor, complete: candidate.complete, entries }
}
