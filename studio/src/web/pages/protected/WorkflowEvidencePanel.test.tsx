import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WorkflowEvidencePanel, type WorkflowEvidenceProjection } from './WorkflowEvidencePanel'

const digest = (character: string) => `sha256:${character.repeat(64)}`

const READY: WorkflowEvidenceProjection = {
  status: 'ready',
  replayCursor: 'pgseq-4',
  complete: true,
  entries: [
    { kind: 'node', sequence: 2, eventId: 'evt-prisma', persisted: true, state: 'succeeded', checkpointRef: 'chk-2', evidenceDigest: digest('a'), workClass: 'model_call', modelCall: true, nodePath: 'prisma_repair', agentId: 'prisma' },
    { kind: 'node', sequence: 3, eventId: 'evt-vale', persisted: true, state: 'succeeded', checkpointRef: 'chk-3', evidenceDigest: digest('b'), workClass: 'deterministic_function', modelCall: false, nodePath: 'vale_verify', deterministicComponentId: 'vale' },
    { kind: 'approval_interrupt', sequence: 4, eventId: 'evt-production-approval', persisted: true, state: 'interrupted', checkpointRef: 'chk-4', evidenceDigest: digest('c'), approvalKind: 'production_approval', interruptId: 'int-production', resumeChannel: 'approval_endpoint', subjectDigest: digest('d'), decision: 'pending' },
  ],
}

describe('WorkflowEvidencePanel', () => {
  it('distinguishes persisted model, deterministic, and approval evidence', () => {
    render(<WorkflowEvidencePanel evidence={READY} />)
    expect(screen.getByRole('heading', { name: 'Persisted workflow replay' })).toBeVisible()
    expect(screen.getByText('MODEL CALL')).toBeVisible()
    expect(screen.getByText('DETERMINISTIC')).toBeVisible()
    expect(screen.getByText('HUMAN GATE')).toBeVisible()
    expect(screen.getByText('pending · separate approval endpoint · interrupted')).toBeVisible()
    const timeline = screen.getByRole('list', { name: 'Persisted workflow evidence in sequence order' })
    expect(timeline).toHaveTextContent('prisma_repair')
    expect(timeline).toHaveTextContent('vale_verify')
    expect(timeline).toHaveTextContent('production approval')
    expect(screen.getByText('Model calls').nextElementSibling).toHaveTextContent('1')
    expect(screen.getByText('Deterministic nodes').nextElementSibling).toHaveTextContent('1')
  })

  it('withholds claims when the private projection is unavailable', () => {
    render(<WorkflowEvidencePanel evidence={{ status: 'unavailable' }} />)
    expect(screen.getByRole('heading', { name: 'Workflow evidence unavailable' })).toBeVisible()
    expect(screen.getByText(/claims are withheld/)).toBeVisible()
    expect(screen.queryByText('MODEL CALL')).not.toBeInTheDocument()
  })

  it('fails closed on non-contiguous or contradictory replay evidence', () => {
    const invalid = {
      ...READY,
      entries: [READY.entries[0], { ...READY.entries[1], sequence: 4 }],
    } as WorkflowEvidenceProjection
    render(<WorkflowEvidencePanel evidence={invalid} />)
    expect(screen.getByRole('alert')).toHaveTextContent('workflow_projection_sequence')
    expect(screen.queryByText('DETERMINISTIC')).not.toBeInTheDocument()
  })
})
