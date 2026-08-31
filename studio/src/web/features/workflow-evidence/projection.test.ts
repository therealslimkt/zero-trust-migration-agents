import { describe, expect, it } from 'vitest'

import { parseWorkflowEvidenceProjection } from './projection'

const digest = (character: string) => `sha256:${character.repeat(64)}`

const ready = {
  status: 'ready',
  replayCursor: 'pgseq-2',
  complete: true,
  entries: [
    { kind: 'node', sequence: 1, eventId: 'evt-prisma', persisted: true, state: 'succeeded', evidenceDigest: digest('a'), workClass: 'model_call', modelCall: true, nodePath: 'prisma_repair', agentId: 'prisma' },
    { kind: 'approval_interrupt', sequence: 2, eventId: 'evt-approval', persisted: true, state: 'interrupted', evidenceDigest: digest('b'), approvalKind: 'production_approval', interruptId: 'int-production', resumeChannel: 'approval_endpoint', subjectDigest: digest('c'), decision: 'pending' },
  ],
}

describe('parseWorkflowEvidenceProjection', () => {
  it('accepts only an ordered persisted projection', () => {
    expect(parseWorkflowEvidenceProjection(ready)).toMatchObject({ status: 'ready', replayCursor: 'pgseq-2' })
  })

  it.each([
    { ...ready, entries: [] },
    { ...ready, entries: [{ ...ready.entries[0], persisted: false }] },
    { ...ready, entries: [{ ...ready.entries[0], sequence: 2 }] },
    { ...ready, entries: [{ ...ready.entries[0], evidenceDigest: 'not-a-digest' }] },
    { ...ready, entries: [{ ...ready.entries[0], modelCall: false }] },
  ])('fails closed for a malformed projection', (candidate) => {
    expect(parseWorkflowEvidenceProjection(candidate)).toEqual({ status: 'unavailable' })
  })
})
