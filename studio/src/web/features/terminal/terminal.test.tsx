import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { WEB_SCHEMA_VERSION, type TerminalFrame } from '../../contracts.generated'
import { TerminalFrameRenderer } from './TerminalFrameRenderer'
import { appendTerminalFrame, parseTerminalFrameSSEBlock } from './stream'

const FRAME: TerminalFrame = {
  schemaVersion: WEB_SCHEMA_VERSION,
  frameId: 'frm_sourceframe001',
  runId: 'mig_liveTerminal001',
  sourceId: 'jde',
  globalSequence: 7,
  laneSequence: 2,
  timestamp: '2026-08-27T10:00:00Z',
  lane: 'source',
  stream: 'stdout',
  producer: 'legacy-jde-db',
  tool: 'db2-cli',
  line: 'AN8  00000123  status=READY',
  severity: 'info',
  evidenceReferences: [],
}

describe('terminal SSE parsing', () => {
  it('accepts the typed terminal event only when SSE and payload identity agree', () => {
    const block = `id: ${FRAME.frameId}\nevent: terminal.frame\ndata: ${JSON.stringify(FRAME)}`
    expect(parseTerminalFrameSSEBlock(block, { runId: FRAME.runId, sourceId: 'jde' })).toEqual(FRAME)
    expect(parseTerminalFrameSSEBlock(block, { runId: FRAME.runId, sourceId: 'dynamics' })).toBeUndefined()
    expect(parseTerminalFrameSSEBlock(block.replace('terminal.frame', 'migration.event'))).toBeUndefined()
    expect(parseTerminalFrameSSEBlock(block.replace(FRAME.frameId, 'frm_differentframe01'))).toBeUndefined()
  })

  it('rejects unknown members, multiline output, malformed timestamps, and invalid evidence', () => {
    const event = (frame: unknown) => `id: ${FRAME.frameId}\nevent: terminal.frame\ndata: ${JSON.stringify(frame)}`
    expect(parseTerminalFrameSSEBlock(event({ ...FRAME, unexpected: true }))).toBeUndefined()
    expect(parseTerminalFrameSSEBlock(event({ ...FRAME, line: 'first\nsecond' }))).toBeUndefined()
    expect(parseTerminalFrameSSEBlock(event({ ...FRAME, timestamp: 'yesterday' }))).toBeUndefined()
    expect(parseTerminalFrameSSEBlock(event({ ...FRAME, evidenceReferences: [{ artifactId: 'artifact-1', kind: 'audit_log', digest: 'not-a-digest' }] }))).toBeUndefined()
  })

  it('deduplicates and bounds validated reconnect replay', () => {
    expect(appendTerminalFrame([FRAME], FRAME)).toEqual([FRAME])
    const next = { ...FRAME, frameId: 'frm_sourceframe002', globalSequence: 8, laneSequence: 3 }
    expect(appendTerminalFrame([FRAME], next, 1)).toEqual([next])
  })
})

describe('TerminalFrameRenderer', () => {
  it('renders the exact producer-admitted line and real producer/tool metadata', () => {
    const { container } = render(<TerminalFrameRenderer lane="source" label="Source VM" feed={{ mode: 'live', connection: 'live', frames: [FRAME], cursor: FRAME.frameId }} />)
    expect(screen.getByRole('log', { name: 'Source VM exact terminal frames' })).toBeVisible()
    expect(screen.getByRole('log')).toHaveAttribute('aria-live', 'off')
    expect(container.querySelector('.live-terminal-frame__line')).toHaveTextContent(FRAME.line, { normalizeWhitespace: false })
    expect(screen.getByText('legacy-jde-db')).toBeVisible()
    expect(screen.getByText('db2-cli')).toBeVisible()
  })

  it('labels empty and replay states without synthesizing output', () => {
    const view = render(<TerminalFrameRenderer lane="compiler" label="Compiler" feed={{ mode: 'live', connection: 'connecting', frames: [] }} />)
    expect(screen.getByRole('status')).toHaveTextContent('CONNECTING · WAITING FOR PRODUCER-ADMITTED FRAMES')
    expect(screen.getByText('No output is synthesized while the stream is empty.')).toBeVisible()

    view.rerender(<TerminalFrameRenderer lane="compiler" label="Compiler" feed={{ mode: 'replay', connection: 'offline', frames: [] }} />)
    expect(screen.getByRole('status')).toHaveTextContent('RECORDED REPLAY · NO EXACT TERMINAL FRAMES WERE CAPTURED')
  })
})
