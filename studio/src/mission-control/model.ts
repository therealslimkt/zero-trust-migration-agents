/**
 * Deterministic frontend domain model for the migration control plane.
 *
 * Wire types in this file mirror contracts/openapi.json and its referenced
 * JSON Schemas at version 1.0.0. View construction never advances state or
 * fabricates progress: the run owns counters/state and the persisted event
 * order owns evidence and activity history.
 */

export const MIGRATION_SCHEMA_VERSION = "1.0.0" as const;

export type SourceId = "jde" | "maxdb" | "btrieve";

export type SourceHostname = "legacy-jde-db" | "legacy-maxdb" | "legacy-btrieve-db";

export type RunState =
  | "created"
  | "inventorying"
  | "redacting"
  | "planning"
  | "awaiting_approval"
  | "approved"
  | "executing"
  | "verifying"
  | "completed"
  | "failed"
  | "cancelled";

export type EvidenceKind =
  | "source_manifest"
  | "redaction_report"
  | "transform_plan"
  | "dataflow_job"
  | "bigquery_table"
  | "reconciliation"
  | "audit_log";

export type SourceEventType =
  | "source.inventory.started"
  | "source.inventory.completed"
  | "source.redaction.completed"
  | "source.plan.ready"
  | "source.execution.started"
  | "source.execution.completed"
  | "source.verification.completed"
  | "source.failed";

export type PortfolioEventType =
  | "migration.created"
  | "portfolio.awaiting_approval"
  | "portfolio.approved"
  | "portfolio.rejected"
  | "migration.completed"
  | "migration.failed"
  | "migration.cancelled";

export type SseEventType = SourceEventType | PortfolioEventType;

export interface SourceDescriptor {
  sourceId: SourceId;
  hostname: SourceHostname;
}

export interface CreateMigrationRequest {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  portfolioName: string;
  sources: SourceDescriptor[];
  requestedBy?: string;
}

export interface SourceProgress {
  sourceId: SourceId;
  hostname: SourceHostname;
  state: RunState;
  recordsRead: number;
  recordsWritten: number;
  recordsRejected: number;
  planDigest?: string;
  failureCode?: string;
}

export interface MigrationRun {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  runId: string;
  portfolioName: string;
  state: RunState;
  sources: SourceProgress[];
  portfolioPlanDigest?: string;
  createdAt: string;
  updatedAt: string;
  failureCode?: string;
}

export interface ApprovalRequest {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  planDigest: string;
  decision: "approve" | "reject";
  decidedBy: string;
  reason?: string;
}

export interface ApprovalResponse {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  approvalId: string;
  runId: string;
  planDigest: string;
  decision: "approve" | "reject";
  resultingState: "approved" | "cancelled";
  decidedBy: string;
  decidedAt: string;
}

export interface EvidenceReference {
  artifactId: string;
  kind: EvidenceKind;
  digest: string;
}

interface SseEventBase {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  eventId: string;
  runId: string;
  timestamp: string;
  summary: string;
  evidenceReferences: EvidenceReference[];
  state: RunState;
}

export interface SourceSseEvent extends SseEventBase {
  sourceId: SourceId;
  eventType: SourceEventType;
}

export interface PortfolioSseEvent extends SseEventBase {
  sourceId?: never;
  eventType: PortfolioEventType;
}

export type MigrationSseEvent = SourceSseEvent | PortfolioSseEvent;
export type SseEvent = MigrationSseEvent;

export interface ProblemDetails {
  schemaVersion: typeof MIGRATION_SCHEMA_VERSION;
  type: string;
  title: string;
  status: number;
  detail?: string;
  requestId?: string;
}

export const SOURCE_ORDER = ["jde", "maxdb", "btrieve"] as const satisfies readonly SourceId[];

export interface SourcePresentation {
  hostname: SourceHostname;
  humanLabel: string;
  legacyDatabase: string;
  encoding: string;
  bigQueryDestination: string;
}

export const SOURCE_PRESENTATION: Readonly<Record<SourceId, Readonly<SourcePresentation>>> =
  Object.freeze({
    jde: Object.freeze({
      hostname: "legacy-jde-db",
      humanLabel: "JD Edwards World",
      legacyDatabase: "IBM Db2 for i / AS/400",
      encoding: "EBCDIC + packed decimal",
      bigQueryDestination: "legacy_migration.jde_f0101",
    }),
    maxdb: Object.freeze({
      hostname: "legacy-maxdb",
      humanLabel: "SAP ERP",
      legacyDatabase: "SAP MaxDB 7.9",
      encoding: "ASCII / binary",
      bigQueryDestination: "legacy_migration.sap_kna1",
    }),
    btrieve: Object.freeze({
      hostname: "legacy-btrieve-db",
      humanLabel: "Sage Accpac",
      legacyDatabase: "Pervasive Btrieve",
      encoding: "Btrieve page binary",
      bigQueryDestination: "legacy_migration.accpac_arcus",
    }),
  });

export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "stale"
  | "disconnected";

export interface MigrationCounts {
  read: number;
  written: number;
  rejected: number;
}

export interface MissionEvidence extends EvidenceReference {
  eventId: string;
  eventType: SseEventType;
  timestamp: string;
  summary: string;
  sourceId?: SourceId;
}

export interface MigrationLaneView {
  sourceId: SourceId;
  presentation: Readonly<SourcePresentation>;
  state: RunState;
  phaseLabel: string;
  counts: Readonly<MigrationCounts>;
  planDigest?: string;
  evidence: readonly MissionEvidence[];
  events: readonly SourceSseEvent[];
  latestEvent?: SourceSseEvent;
  failureCode?: string;
  blocked: boolean;
}

export type ApprovalBlocker =
  | "run_not_awaiting_approval"
  | "source_not_awaiting_approval"
  | "portfolio_digest_invalid"
  | "source_digest_invalid"
  | "failure_detected"
  | "connection_stale"
  | "connection_disconnected";

export interface MissionControlView {
  runId: string;
  portfolioName: string;
  state: RunState;
  phaseLabel: string;
  planDigest?: string;
  failureCode?: string;
  blocked: boolean;
  approvalEnabled: boolean;
  approvalBlockers: readonly ApprovalBlocker[];
  connectionState: ConnectionState;
  lanes: readonly MigrationLaneView[];
  portfolioEvidence: readonly MissionEvidence[];
  portfolioEvents: readonly PortfolioSseEvent[];
  latestEvent?: MigrationSseEvent;
  createdAt: string;
  updatedAt: string;
}

export type MissionControlModelErrorCode = "invalid_source_set" | "invalid_source_hostname";

export class MissionControlModelError extends Error {
  readonly code: MissionControlModelErrorCode;

  constructor(code: MissionControlModelErrorCode) {
    super(code === "invalid_source_set" ? "The migration run has an invalid source set." : "A source hostname is invalid.");
    this.name = "MissionControlModelError";
    this.code = code;
  }
}

const SHA256_DIGEST = /^sha256:[a-f0-9]{64}$/;

const PHASE_LABELS: Readonly<Record<RunState, string>> = Object.freeze({
  created: "Created",
  inventorying: "Inventorying",
  redacting: "Redacting at edge",
  planning: "Planning",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  executing: "Executing trusted migration",
  verifying: "Verifying reconciliation",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
});

function isDigest(value: string | undefined): value is string {
  return value !== undefined && SHA256_DIGEST.test(value);
}

function sourceEventsFor(events: readonly MigrationSseEvent[], runId: string, sourceId: SourceId): SourceSseEvent[] {
  return events.filter(
    (event): event is SourceSseEvent => event.runId === runId && event.sourceId === sourceId,
  );
}

function portfolioEventsFor(events: readonly MigrationSseEvent[], runId: string): PortfolioSseEvent[] {
  return events.filter(
    (event): event is PortfolioSseEvent => event.runId === runId && event.sourceId === undefined,
  );
}

function evidenceFor(events: readonly MigrationSseEvent[]): MissionEvidence[] {
  return events.flatMap((event) =>
    event.evidenceReferences.map((evidence) => ({
      ...evidence,
      eventId: event.eventId,
      eventType: event.eventType,
      timestamp: event.timestamp,
      summary: event.summary,
      ...(event.sourceId === undefined ? {} : { sourceId: event.sourceId }),
    })),
  );
}

function validateAndOrderSources(sources: readonly SourceProgress[]): SourceProgress[] {
  if (sources.length !== SOURCE_ORDER.length) {
    throw new MissionControlModelError("invalid_source_set");
  }

  const byId = new Map<SourceId, SourceProgress>();
  for (const source of sources) {
    if (byId.has(source.sourceId)) {
      throw new MissionControlModelError("invalid_source_set");
    }
    if (source.hostname !== SOURCE_PRESENTATION[source.sourceId].hostname) {
      throw new MissionControlModelError("invalid_source_hostname");
    }
    byId.set(source.sourceId, source);
  }

  return SOURCE_ORDER.map((sourceId) => {
    const source = byId.get(sourceId);
    if (source === undefined) {
      throw new MissionControlModelError("invalid_source_set");
    }
    return source;
  });
}

function approvalBlockersFor(
  state: RunState,
  planDigest: string | undefined,
  lanes: readonly MigrationLaneView[],
  connectionState: ConnectionState,
  failureDetected: boolean,
): ApprovalBlocker[] {
  const blockers: ApprovalBlocker[] = [];
  if (state !== "awaiting_approval") blockers.push("run_not_awaiting_approval");
  if (!lanes.every((lane) => lane.state === "awaiting_approval")) blockers.push("source_not_awaiting_approval");
  if (!isDigest(planDigest)) blockers.push("portfolio_digest_invalid");
  if (!lanes.every((lane) => isDigest(lane.planDigest))) blockers.push("source_digest_invalid");
  if (failureDetected) blockers.push("failure_detected");
  if (connectionState === "stale") blockers.push("connection_stale");
  if (connectionState === "disconnected") blockers.push("connection_disconnected");
  return blockers;
}

/**
 * Builds the complete, canonical three-lane Mission Control projection.
 * Events retain their caller-supplied persisted order. Events for another run
 * are ignored so activity from a previous selection cannot be misattributed.
 */
export function buildMissionControlView(
  run: MigrationRun,
  events: readonly MigrationSseEvent[],
  connectionState: ConnectionState = "connected",
): MissionControlView {
  const orderedSources = validateAndOrderSources(run.sources);
  const portfolioEvents = portfolioEventsFor(events, run.runId);
  const relevantEvents = events.filter((event) => event.runId === run.runId);
  const portfolioFailedByEvent = portfolioEvents.some(
    (event) => event.eventType === "migration.failed" || event.eventType === "migration.cancelled",
  );

  const lanes: MigrationLaneView[] = orderedSources.map((source) => {
    const sourceEvents = sourceEventsFor(events, run.runId, source.sourceId);
    const failedByEvent = sourceEvents.some((event) => event.eventType === "source.failed");
    const blocked =
      failedByEvent ||
      source.state === "failed" ||
      source.state === "cancelled" ||
      run.state === "failed" ||
      run.state === "cancelled";
    const latestEvent = sourceEvents.at(-1);

    return {
      sourceId: source.sourceId,
      presentation: SOURCE_PRESENTATION[source.sourceId],
      state: source.state,
      phaseLabel: PHASE_LABELS[source.state],
      counts: Object.freeze({
        read: source.recordsRead,
        written: source.recordsWritten,
        rejected: source.recordsRejected,
      }),
      ...(source.planDigest === undefined ? {} : { planDigest: source.planDigest }),
      evidence: Object.freeze(evidenceFor(sourceEvents)),
      events: Object.freeze(sourceEvents),
      ...(latestEvent === undefined ? {} : { latestEvent }),
      ...(source.failureCode === undefined ? {} : { failureCode: source.failureCode }),
      blocked,
    };
  });

  const failureDetected =
    run.state === "failed" ||
    run.failureCode !== undefined ||
    portfolioFailedByEvent ||
    lanes.some((lane) => lane.blocked || lane.failureCode !== undefined);
  const approvalBlockers = approvalBlockersFor(
    run.state,
    run.portfolioPlanDigest,
    lanes,
    connectionState,
    failureDetected,
  );
  const latestEvent = relevantEvents.at(-1);

  return {
    runId: run.runId,
    portfolioName: run.portfolioName,
    state: run.state,
    phaseLabel: PHASE_LABELS[run.state],
    ...(run.portfolioPlanDigest === undefined ? {} : { planDigest: run.portfolioPlanDigest }),
    ...(run.failureCode === undefined ? {} : { failureCode: run.failureCode }),
    blocked: run.state === "failed" || run.state === "cancelled" || portfolioFailedByEvent,
    approvalEnabled: approvalBlockers.length === 0,
    approvalBlockers: Object.freeze(approvalBlockers),
    connectionState,
    lanes: Object.freeze(lanes),
    portfolioEvidence: Object.freeze(evidenceFor(portfolioEvents)),
    portfolioEvents: Object.freeze(portfolioEvents),
    ...(latestEvent === undefined ? {} : { latestEvent }),
    createdAt: run.createdAt,
    updatedAt: run.updatedAt,
  };
}

/** Re-evaluates the immutable approval conditions from the view itself. */
export function canApprove(view: MissionControlView): boolean {
  return (
    view.state === "awaiting_approval" &&
    isDigest(view.planDigest) &&
    view.lanes.length === SOURCE_ORDER.length &&
    view.lanes.every(
      (lane, index) =>
        lane.sourceId === SOURCE_ORDER[index] &&
        lane.state === "awaiting_approval" &&
        isDigest(lane.planDigest) &&
        !lane.blocked &&
        lane.failureCode === undefined,
    ) &&
    !view.blocked &&
    view.failureCode === undefined &&
    view.connectionState !== "stale" &&
    view.connectionState !== "disconnected" &&
    view.approvalBlockers.length === 0
  );
}
