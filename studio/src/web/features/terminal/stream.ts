import { WEB_SCHEMA_VERSION, type SourceId, type TerminalFrame } from '../../contracts.generated'

const FRAME_ID = /^frm_[A-Za-z0-9]{12,64}$/
const RUN_ID = /^mig_[A-Za-z0-9]{12,64}$/
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/
const DIGEST = /^sha256:[0-9a-f]{64}$/
const LANES = new Set(['source', 'edge', 'compiler', 'destination'])
const STREAMS = new Set(['command', 'stdout', 'stderr', 'system', 'metric'])
const SEVERITIES = new Set(['debug', 'info', 'warning', 'error'])
const EVIDENCE_KINDS = new Set(['source_manifest', 'redaction_report', 'transform_plan', 'dataflow_job', 'bigquery_table', 'reconciliation', 'audit_log'])
const FRAME_KEYS = new Set(['schemaVersion', 'frameId', 'runId', 'sourceId', 'globalSequence', 'laneSequence', 'timestamp', 'lane', 'stream', 'producer', 'tool', 'line', 'severity', 'evidenceReferences'])

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function boundedSingleLine(value: unknown, maximum: number): value is string {
  if (typeof value !== 'string' || value.length < 1 || value.length > maximum || value.includes('\n') || value.includes('\r')) return false
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0
    if ((code < 0x20 && character !== '\t') || code === 0x7f) return false
  }
  return true
}

function isEvidenceReference(value: unknown): boolean {
  if (!isObject(value) || Object.keys(value).length !== 3) return false
  return boundedSingleLine(value.artifactId, 200) && EVIDENCE_KINDS.has(String(value.kind)) &&
    typeof value.digest === 'string' && DIGEST.test(value.digest)
}

function isTerminalFrame(value: unknown): value is TerminalFrame {
  if (!isObject(value)) return false
  if (
    Object.keys(value).length !== FRAME_KEYS.size || Object.keys(value).some((key) => !FRAME_KEYS.has(key)) ||
    value.schemaVersion !== WEB_SCHEMA_VERSION ||
    typeof value.frameId !== 'string' || !FRAME_ID.test(value.frameId) ||
    typeof value.runId !== 'string' || !RUN_ID.test(value.runId) ||
    !['jde', 'maxdb', 'btrieve'].includes(String(value.sourceId)) ||
    !Number.isSafeInteger(value.globalSequence) || Number(value.globalSequence) < 1 ||
    !Number.isSafeInteger(value.laneSequence) || Number(value.laneSequence) < 1 ||
    typeof value.timestamp !== 'string' || !TIMESTAMP.test(value.timestamp) || Number.isNaN(Date.parse(value.timestamp)) ||
    !LANES.has(String(value.lane)) ||
    !STREAMS.has(String(value.stream)) ||
    !boundedSingleLine(value.producer, 160) ||
    !boundedSingleLine(value.tool, 200) ||
    !boundedSingleLine(value.line, 4_096) ||
    !SEVERITIES.has(String(value.severity)) ||
    !Array.isArray(value.evidenceReferences) || value.evidenceReferences.length > 20
  ) return false

  return value.evidenceReferences.every(isEvidenceReference)
}

export interface TerminalFrameExpectation {
  readonly runId: string
  readonly sourceId: SourceId
}

/** Parses one complete SSE block without advancing a cursor for malformed data. */
export function parseTerminalFrameSSEBlock(block: string, expected?: TerminalFrameExpectation): TerminalFrame | undefined {
  let id: string | undefined
  let eventName: string | undefined
  const data: string[] = []

  for (const line of block.replaceAll('\r\n', '\n').split('\n')) {
    if (line.startsWith('id:')) id = line.slice(3).trim()
    else if (line.startsWith('event:')) eventName = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }

  if (!id || !FRAME_ID.test(id) || eventName !== 'terminal.frame' || data.length === 0) return undefined
  try {
    const frame: unknown = JSON.parse(data.join('\n'))
    if (!isTerminalFrame(frame) || frame.frameId !== id) return undefined
    if (expected && (frame.runId !== expected.runId || frame.sourceId !== expected.sourceId)) return undefined
    return frame
  } catch {
    return undefined
  }
}

export function appendTerminalFrame(current: readonly TerminalFrame[], frame: TerminalFrame, limit = 500): readonly TerminalFrame[] {
  if (current.some((item) => item.frameId === frame.frameId)) return current
  const next = [...current, frame].sort((left, right) => left.globalSequence - right.globalSequence)
  return next.length > limit ? next.slice(next.length - limit) : next
}
