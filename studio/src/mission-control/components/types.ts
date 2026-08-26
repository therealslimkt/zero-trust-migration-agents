/**
 * Presentation-side view of the Mission Control domain layer.
 *
 * The domain layer (`../model`, `../client`) is built concurrently and owns all
 * state derivation. This file only declares the shape the UI reads, so there is
 * exactly one integration seam (the casts in `App.tsx`) instead of dozens of
 * guessed field accesses spread through the components. Every field the wire
 * contract marks optional stays optional here, and the UI renders an explicit
 * "unavailable" state rather than inventing a value.
 *
 * Names follow `contracts/schemas/common.schema.json`.
 */
import type { SourceId } from '../model';

export const RUN_STATES = [
  'created',
  'inventorying',
  'redacting',
  'planning',
  'awaiting_approval',
  'approved',
  'executing',
  'verifying',
  'completed',
  'failed',
  'cancelled',
] as const;

export type RunState = (typeof RUN_STATES)[number];

export const EVIDENCE_KINDS = [
  'source_manifest',
  'redaction_report',
  'transform_plan',
  'dataflow_job',
  'bigquery_table',
  'reconciliation',
  'audit_log',
] as const;

export type EvidenceKind = (typeof EVIDENCE_KINDS)[number];

export interface EvidenceReferenceView {
  artifactId: string;
  kind: EvidenceKind | string;
  digest: string;
}

export interface MissionEventView {
  eventId: string;
  runId?: string;
  sourceId?: SourceId;
  eventType: string;
  timestamp: string;
  summary: string;
  evidenceReferences?: EvidenceReferenceView[];
  state?: RunState;
}

export interface LaneView {
  sourceId: SourceId;
  hostname?: string;
  state?: RunState;
  recordsRead?: number;
  recordsWritten?: number;
  recordsRejected?: number;
  planDigest?: string;
  failureCode?: string;
  /** Preferred when the domain layer already aggregates lane evidence. */
  evidence?: EvidenceReferenceView[];
  events?: MissionEventView[];
}

export interface MissionControlView {
  runId?: string;
  portfolioName?: string;
  state?: RunState;
  portfolioPlanDigest?: string;
  /** Alias tolerated while the domain layer settles on a digest field name. */
  planDigest?: string;
  failureCode?: string;
  createdAt?: string;
  updatedAt?: string;
  /** Echo of the `connectionState` argument passed to `buildMissionControlView`. */
  connectionState?: string;
  connection?: { status?: string; lastEventAt?: string };
  lanes?: LaneView[];
  /** Alias tolerated for the same reason as `planDigest`. */
  sources?: LaneView[];
  events?: MissionEventView[];
}

/** How the UI describes the event channel. Domain values are normalised into this. */
export type ConnectionStatus =
  | 'unconfigured'
  | 'connecting'
  | 'live'
  | 'stale'
  | 'disconnected'
  | 'failed';

export interface SourcePresentationView {
  label: string;
  shortLabel: string;
  hostname: string;
  legacyFormat: string;
  bigQueryTarget: string;
}

/** One canonical lane, resolved against `SOURCE_ORDER` so all three always render. */
export interface LaneSummary {
  sourceId: SourceId;
  presentation: SourcePresentationView;
  lane?: LaneView;
  evidence: EvidenceReferenceView[];
}

/** Matches `contracts/schemas/approval-request.schema.json` minus `schemaVersion`. */
export interface PortfolioDecisionInput {
  planDigest: string;
  decision: 'approve' | 'reject';
  decidedBy: string;
  reason?: string;
}

export interface MissionControlSnapshot {
  run: unknown;
  events: unknown[];
  connectionState?: string;
}

/**
 * The client surface `App.tsx` consumes. The domain `MissionControlClient` is
 * expected to satisfy this; `start`/`stop` are invoked defensively so a client
 * that connects eagerly in its constructor still works.
 */
export interface MissionControlClientLike {
  subscribe(listener: (snapshot: MissionControlSnapshot) => void): (() => void) | void;
  start?(): void;
  stop?(): void;
  submitDecision(input: PortfolioDecisionInput): Promise<unknown>;
}
