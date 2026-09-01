/**
 * Display-only helpers: labels, formatting, and thin selectors over the domain
 * view. Nothing here decides run state, approval eligibility, or reconciliation
 * — those come from `../model`.
 */
import { SOURCE_PRESENTATION } from '../model';
import type { SourceId } from '../model';
import type {
  ConnectionStatus,
  EvidenceReferenceView,
  LaneView,
  MissionControlView,
  MissionEventView,
  RunState,
  SourcePresentationView,
} from './types';

export type Tone = 'neutral' | 'progress' | 'attention' | 'positive' | 'critical';

export const UNAVAILABLE = '—';

export const RUN_STATE_LABEL: Record<RunState, string> = {
  created: 'Registered',
  inventorying: 'Reading source',
  redacting: 'Protecting at edge',
  planning: 'Planning transform',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  executing: 'Executing',
  verifying: 'Verifying',
  completed: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export const RUN_STATE_TONE: Record<RunState, Tone> = {
  created: 'neutral',
  inventorying: 'progress',
  redacting: 'progress',
  planning: 'progress',
  awaiting_approval: 'attention',
  approved: 'positive',
  executing: 'progress',
  verifying: 'progress',
  completed: 'positive',
  failed: 'critical',
  cancelled: 'critical',
};

export const EVENT_TYPE_LABEL: Record<string, string> = {
  'source.inventory.started': 'Inventory started',
  'source.inventory.completed': 'Inventory completed',
  'source.redaction.completed': 'Edge protection completed',
  'source.plan.ready': 'Transform plan ready',
  'source.execution.started': 'Execution started',
  'source.execution.completed': 'Execution completed',
  'source.verification.completed': 'Verification completed',
  'source.failed': 'Source failed',
  'migration.created': 'Portfolio created',
  'portfolio.awaiting_approval': 'Portfolio awaiting approval',
  'portfolio.approved': 'Portfolio approved',
  'portfolio.rejected': 'Portfolio rejected',
  'migration.completed': 'Portfolio completed',
  'migration.failed': 'Portfolio failed',
  'migration.cancelled': 'Portfolio cancelled',
};

export const EVIDENCE_KIND_LABEL: Record<string, string> = {
  source_manifest: 'Source manifest',
  redaction_report: 'Redaction report',
  transform_plan: 'Transform plan',
  dataflow_job: 'Dataflow job',
  bigquery_table: 'BigQuery table',
  reconciliation: 'Reconciliation',
  audit_log: 'Audit log',
};

/**
 * A rendering of the canonical `runState` enum as an ordered lane track. This is
 * presentation only: no state is advanced here, and `failed`/`cancelled` fall
 * off the track rather than mapping onto a stage.
 */
export const LANE_STAGES: ReadonlyArray<{ id: string; label: string; states: RunState[] }> = [
  { id: 'connect', label: 'Connect', states: ['created'] },
  { id: 'read', label: 'Read', states: ['inventorying'] },
  { id: 'protect', label: 'Protect', states: ['redacting'] },
  { id: 'plan', label: 'Plan', states: ['planning'] },
  { id: 'approve', label: 'Approve', states: ['awaiting_approval', 'approved'] },
  { id: 'execute', label: 'Execute', states: ['executing'] },
  { id: 'verify', label: 'Verify', states: ['verifying'] },
  { id: 'land', label: 'Land', states: ['completed'] },
];

export type StageStatus = 'done' | 'current' | 'pending' | 'halted';

export function stageStatuses(state?: RunState): StageStatus[] {
  if (state === 'failed' || state === 'cancelled') {
    return LANE_STAGES.map(() => 'halted');
  }
  const current = LANE_STAGES.findIndex((stage) => state !== undefined && stage.states.includes(state));
  if (current < 0) {
    return LANE_STAGES.map(() => 'pending');
  }
  return LANE_STAGES.map((_, index) => {
    if (index < current) return 'done';
    if (index === current) return 'current';
    return 'pending';
  });
}

const countFormatter = new Intl.NumberFormat('en-US');

export function formatCount(value?: number): string {
  return typeof value === 'number' && Number.isFinite(value) ? countFormatter.format(value) : UNAVAILABLE;
}

/** `sha256:8d1f0c3a91b4…` — the full digest is always available on demand. */
export function abbreviateDigest(digest?: string): string {
  if (!digest) return UNAVAILABLE;
  const [prefix, hex] = digest.includes(':') ? digest.split(':', 2) : ['', digest];
  if (!hex) return digest;
  const head = hex.slice(0, 12);
  return prefix ? `${prefix}:${head}…` : `${head}…`;
}

export function formatTimestamp(iso?: string): string {
  if (!iso) return UNAVAILABLE;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatDateTime(iso?: string): string {
  if (!iso) return UNAVAILABLE;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString();
}

export function eventTypeLabel(eventType: string): string {
  return EVENT_TYPE_LABEL[eventType] ?? eventType;
}

export function evidenceKindLabel(kind: string): string {
  return EVIDENCE_KIND_LABEL[kind] ?? kind;
}

/** Failure codes arrive as `SCREAMING_SNAKE`; render them as readable text. */
export function humaniseCode(code?: string): string {
  if (!code) return UNAVAILABLE;
  return code.toLowerCase().replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

/** Map the frozen domain presentation into the compact UI labels. */
export function presentationFor(sourceId: SourceId): SourcePresentationView {
  const raw = SOURCE_PRESENTATION[sourceId];
  const label = raw.humanLabel;
  return {
    label,
    shortLabel: sourceId === 'jde' ? 'JDE' : sourceId === 'dynamics' ? 'Dynamics AX' : 'Oracle EBS',
    hostname: raw.hostname,
    legacyFormat: `${raw.legacyDatabase} · ${raw.encoding}`,
    bigQueryTarget: raw.bigQueryDestination,
  };
}

export function selectLanes(view: MissionControlView | null): Map<SourceId, LaneView> {
  const lanes = view?.lanes ?? [];
  const byId = new Map<SourceId, LaneView>();
  for (const lane of lanes) {
    byId.set(lane.sourceId, {
      sourceId: lane.sourceId,
      hostname: lane.presentation.hostname,
      state: lane.state,
      recordsRead: lane.counts.read,
      recordsWritten: lane.counts.written,
      recordsRejected: lane.counts.rejected,
      ...(lane.planDigest === undefined ? {} : { planDigest: lane.planDigest }),
      ...(lane.failureCode === undefined ? {} : { failureCode: lane.failureCode }),
      evidence: [...lane.evidence],
      events: [...lane.events],
    });
  }
  return byId;
}

export function selectPortfolioDigest(view: MissionControlView | null): string | undefined {
  return view?.planDigest;
}

export function selectConnectionStatus(
  view: MissionControlView | null,
  fallback: ConnectionStatus,
): ConnectionStatus {
  const raw = (view?.connectionState ?? '').toLowerCase();
  switch (raw) {
    case 'live':
    case 'open':
    case 'connected':
    case 'streaming':
      return 'live';
    case 'connecting':
    case 'reconnecting':
      return 'connecting';
    case 'stale':
    case 'degraded':
      return 'stale';
    case 'disconnected':
    case 'closed':
    case 'offline':
      return 'disconnected';
    case 'failed':
    case 'error':
      return 'failed';
    default:
      return fallback;
  }
}

export const CONNECTION_LABEL: Record<ConnectionStatus, string> = {
  unconfigured: 'Not configured',
  connecting: 'Connecting',
  live: 'Live',
  stale: 'Stale stream',
  disconnected: 'Disconnected',
  failed: 'Stream failed',
};

export const CONNECTION_TONE: Record<ConnectionStatus, Tone> = {
  unconfigured: 'neutral',
  connecting: 'progress',
  live: 'positive',
  stale: 'attention',
  disconnected: 'critical',
  failed: 'critical',
};

/** Evidence references the backend actually emitted for one lane, de-duplicated. */
export function laneEvidence(lane: LaneView | undefined, events: MissionEventView[]): EvidenceReferenceView[] {
  if (lane?.evidence?.length) return dedupeEvidence(lane.evidence);
  if (!lane) return [];
  const collected: EvidenceReferenceView[] = [];
  for (const event of events) {
    if (event.sourceId !== lane.sourceId) continue;
    for (const reference of event.evidenceReferences ?? []) collected.push(reference);
  }
  return dedupeEvidence(collected);
}

function dedupeEvidence(references: EvidenceReferenceView[]): EvidenceReferenceView[] {
  const seen = new Set<string>();
  const unique: EvidenceReferenceView[] = [];
  for (const reference of references) {
    if (!reference?.artifactId || seen.has(reference.artifactId)) continue;
    seen.add(reference.artifactId);
    unique.push(reference);
  }
  return unique;
}

export function distinctKinds(references: EvidenceReferenceView[]): string[] {
  const kinds: string[] = [];
  for (const reference of references) {
    if (reference.kind && !kinds.includes(reference.kind)) kinds.push(reference.kind);
  }
  return kinds;
}
