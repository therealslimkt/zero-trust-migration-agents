import type { ReactNode } from 'react'

import type {
  DeterministicEvidence,
  ModelCallEvidence,
  WorkflowEvidenceProjection,
} from '../../features/workflow-evidence'
import { PixelIcon } from '../../shared/ui'
import './workflow-evidence.css'

export type {
  ApprovalInterruptEvidence,
  DeterministicEvidence,
  ModelCallEvidence,
  WorkflowEvidenceProjection,
} from '../../features/workflow-evidence'

const DIGEST = /^sha256:[a-f0-9]{64}$/
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:/-]{2,255}$/

function invalidProjection(value: WorkflowEvidenceProjection): string | undefined {
  if (value.status === 'unavailable') return undefined
  if (!IDENTIFIER.test(value.replayCursor) || value.entries.length === 0) return 'workflow_projection_shape'
  const eventIds = new Set<string>()
  let previous = value.entries[0].sequence - 1
  for (const entry of value.entries) {
    if (
      !Number.isSafeInteger(entry.sequence) ||
      entry.sequence < 1 ||
      entry.sequence !== previous + 1 ||
      !IDENTIFIER.test(entry.eventId) ||
      eventIds.has(entry.eventId) ||
      entry.persisted !== true ||
      !DIGEST.test(entry.evidenceDigest) ||
      (entry.checkpointRef !== undefined && !IDENTIFIER.test(entry.checkpointRef))
    ) return 'workflow_projection_sequence'
    previous = entry.sequence
    eventIds.add(entry.eventId)
    if (entry.kind === 'node') {
      if (!IDENTIFIER.test(entry.nodePath)) return 'workflow_projection_node'
      if (entry.modelCall) {
        if (entry.workClass !== 'model_call' || !IDENTIFIER.test(entry.agentId)) return 'workflow_projection_model'
      } else if (
        String(entry.workClass) === 'model_call' ||
        !IDENTIFIER.test(entry.deterministicComponentId)
      ) return 'workflow_projection_deterministic'
    } else if (
      entry.resumeChannel !== 'approval_endpoint' ||
      !IDENTIFIER.test(entry.interruptId) ||
      !DIGEST.test(entry.subjectDigest) ||
      (entry.decision === 'pending' && entry.approvalId !== undefined) ||
      (entry.decision !== 'pending' && (entry.approvalId === undefined || !IDENTIFIER.test(entry.approvalId)))
    ) return 'workflow_projection_approval'
  }
  return undefined
}

function Definition({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>
}

export function WorkflowEvidencePanel({ evidence }: { readonly evidence: WorkflowEvidenceProjection }) {
  if (evidence.status === 'unavailable') {
    return (
      <section className="workflow-evidence workflow-evidence--unavailable" aria-labelledby="workflow-evidence-title">
        <h3 id="workflow-evidence-title">Workflow evidence unavailable</h3>
        <p>The authenticated web contract has not supplied a persisted orchestration projection. Model-call, deterministic-node, checkpoint, and approval-interrupt claims are withheld.</p>
      </section>
    )
  }

  const invalid = invalidProjection(evidence)
  if (invalid) {
    return (
      <section className="workflow-evidence workflow-evidence--invalid" role="alert" aria-labelledby="workflow-evidence-title">
        <h3 id="workflow-evidence-title">Workflow evidence rejected</h3>
        <p>{invalid}. The inspector will not infer or repair persisted execution evidence.</p>
      </section>
    )
  }

  const nodes = evidence.entries.filter((entry): entry is ModelCallEvidence | DeterministicEvidence => entry.kind === 'node')
  const modelCalls = nodes.filter((entry) => entry.modelCall).length
  const deterministic = nodes.length - modelCalls
  return (
    <section className="workflow-evidence" aria-labelledby="workflow-evidence-title">
      <header className="workflow-evidence__header">
        <div><h3 id="workflow-evidence-title">Persisted workflow replay</h3><p>Ordered authority evidence; never reconstructed from timestamps or narration.</p></div>
        <span className="workflow-evidence__cursor">cursor {evidence.replayCursor}</span>
      </header>
      <dl className="workflow-evidence__metrics">
        <Definition label="Model calls">{modelCalls}</Definition>
        <Definition label="Deterministic nodes">{deterministic}</Definition>
        <Definition label="Approval interrupts">{evidence.entries.length - nodes.length}</Definition>
        <Definition label="Replay window">{evidence.complete ? 'complete' : 'partial'}</Definition>
      </dl>
      <ol className="workflow-evidence__timeline" aria-label="Persisted workflow evidence in sequence order">
        {evidence.entries.map((entry) => (
          <li key={entry.eventId}>
            <span className="workflow-evidence__sequence">{entry.sequence}</span>
            <div>
              {entry.kind === 'node' ? (
                <>
                  <strong>{entry.nodePath}</strong>
                  <span className={entry.modelCall ? 'workflow-evidence__badge workflow-evidence__badge--model' : 'workflow-evidence__badge'}>
                    {entry.modelCall ? 'MODEL CALL' : 'DETERMINISTIC'}
                  </span>
                  <p>{entry.modelCall ? entry.agentId : entry.deterministicComponentId} · {entry.state}</p>
                </>
              ) : (
                <>
                  <strong>{entry.approvalKind.replace('_', ' ')}</strong>
                  <span className="workflow-evidence__badge workflow-evidence__badge--approval">HUMAN GATE</span>
                  <p>{entry.decision} · separate approval endpoint · {entry.state}</p>
                </>
              )}
              <small>{entry.checkpointRef ?? 'no checkpoint reference'} · {entry.evidenceDigest}</small>
            </div>
            <PixelIcon name={entry.state === 'failed' ? 'cross-pixel' : entry.kind === 'approval_interrupt' ? 'key' : 'check-pixel'} size="xs" color={entry.state === 'failed' ? 'google-red' : entry.kind === 'approval_interrupt' ? 'google-yellow' : 'google-green'} />
          </li>
        ))}
      </ol>
    </section>
  )
}
