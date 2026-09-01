// Generated-style snapshot of contracts/web/v1. Do not merge these types into
// the frozen mission-control model; browser BFF contracts evolve independently.

export const WEB_SCHEMA_VERSION = "1.0.0" as const;
export const WEB_REQUIREMENTS_SHA256 = "37374d4fb13c4fd890e60c07b7d691fec0fe34ac5440b878aa275e5d9f3c0191" as const;

export type ExperienceMode = "recorded_demo" | "live";
export type DataClass = "synthetic_demo" | "private";
export type SourceId = "jde" | "dynamics" | "ebs";
export type TerminalLane = "source" | "edge" | "compiler" | "destination";
export type TerminalStream = "command" | "stdout" | "stderr" | "system" | "metric";
export type TerminalSeverity = "debug" | "info" | "warning" | "error";
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
export type SyntheticValue = string | number | boolean | null;

export interface NamedValue {
  readonly name: string;
  readonly dataType: string;
  readonly value: SyntheticValue;
}

export interface SchemaField {
  readonly name: string;
  readonly dataType: string;
  readonly nullable: boolean;
  readonly description?: string;
}

export interface EvidenceReference {
  readonly artifactId: string;
  readonly kind: EvidenceKind;
  readonly digest: string;
}

export interface Reconciliation {
  readonly status: "matched" | "mismatched";
  readonly recordsRead: number;
  readonly recordsWritten: number;
  readonly recordsRejected: number;
  readonly outputRows: number;
  readonly sourceChecksum: string;
  readonly destinationChecksum: string;
  readonly evidence: EvidenceReference;
}

export interface SourceSample {
  readonly recordId: string;
  readonly rawBytesHex: string;
  readonly decodedFields: readonly NamedValue[];
}

export interface SourceSystemReplay {
  readonly databaseFamily: string;
  readonly databaseVersion: string;
  readonly applicationLayer: string;
  readonly schema: readonly SchemaField[];
  readonly samples: readonly SourceSample[];
  readonly exampleQueries: readonly string[];
}

export interface CompilerAction {
  readonly sequence: number;
  readonly eventId: string;
  readonly timestamp: string;
  readonly stage: "connect" | "read" | "protect" | "plan" | "approve" | "execute" | "verify" | "land";
  readonly agent: string;
  readonly tool: string;
  readonly summary: string;
  readonly result: string;
  readonly evidenceReferences: readonly EvidenceReference[];
}

export interface DeclarativeTransform {
  readonly sequence: number;
  readonly operation: "decode_text" | "packed_decimal" | "map_date" | "rename" | "cast" | "drop" | "tokenize";
  readonly sourceField: string;
  readonly targetField: string;
  readonly encoding?: string;
  readonly targetType?: string;
  readonly format?: string;
}

export interface DriverArtifact {
  readonly coordinates: string;
  readonly version: string;
  readonly sourceUrl: string;
  readonly license: string;
  readonly sha256: string;
  readonly signatureVerified: boolean;
}

export interface RecordedApproval {
  readonly approvalId: string;
  readonly decision: "approved";
  readonly decidedAt: string;
  readonly planDigest: string;
}

export interface CompilerReplay {
  readonly actions: readonly CompilerAction[];
  readonly transforms: readonly DeclarativeTransform[];
  readonly driver: DriverArtifact;
  readonly localGemmaEvidence: EvidenceReference;
  readonly geminiVertexEvidence: EvidenceReference;
  readonly beamTransformIds: readonly string[];
  readonly dataflowJobId: string;
  readonly approval: RecordedApproval;
}

export interface DestinationRow {
  readonly recordId: string;
  readonly fields: readonly NamedValue[];
}

export interface DestinationReplay {
  readonly dataset: string;
  readonly table: string;
  readonly schema: readonly SchemaField[];
  readonly rows: readonly DestinationRow[];
  readonly reconciliation: Reconciliation;
  readonly dataflowEvidence: EvidenceReference;
  readonly bigQueryEvidence: EvidenceReference;
  readonly suggestedQueries: readonly string[];
}

export interface SourceReplay {
  readonly sourceId: SourceId;
  readonly hostname: "legacy-jde-db" | "dynamics-ax" | "oracle-ebs-19c";
  readonly displayName: string;
  readonly source: SourceSystemReplay;
  readonly compiler: CompilerReplay;
  readonly destination: DestinationReplay;
  readonly terminalFrames: readonly TerminalFrame[];
}

export interface ReplayEvent {
  readonly sequence: number;
  readonly eventId: string;
  readonly timestamp: string;
  readonly sourceId?: SourceId;
  readonly eventType: string;
  readonly state: RunState;
  readonly summary: string;
  readonly evidenceReferences: readonly EvidenceReference[];
}

export interface PracticeApproval {
  readonly pauseAfterSequence: number;
  readonly planDigest: string;
  readonly prompt: string;
}

/** Content-addressed, server-validated publication; treat every member as immutable. */
export interface DemoManifest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly demoId: string;
  readonly experienceMode: "recorded_demo";
  readonly dataClass: "synthetic_demo";
  readonly title: string;
  readonly sourceRunId: string;
  readonly runState: "completed";
  readonly portfolioPlanDigest: string;
  readonly publishedAt: string;
  readonly bundleDigest: string;
  readonly practiceApproval: PracticeApproval;
  readonly sources: readonly SourceReplay[];
  readonly events: readonly ReplayEvent[];
  readonly evidence: readonly EvidenceReference[];
  readonly reconciliation: Reconciliation;
}

export interface DemoSummary {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly demoId: string;
  readonly title: string;
  readonly sourceRunId: string;
  readonly publishedAt: string;
  readonly bundleDigest: string;
}

export interface IdentitySummary {
  readonly subject: string;
  readonly displayName: string;
  readonly email: string;
  readonly pictureUrl?: string;
}

export interface SessionResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly authenticated: true;
  readonly user: IdentitySummary;
}

export interface ListDemosResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly demos: readonly DemoSummary[];
}

export interface PublishDemoRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly manifest: DemoManifest;
}

export interface PublishDemoResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly demoId: string;
  readonly publishedAt: string;
  readonly bundleDigest: string;
  readonly location: string;
}

export interface LiveRunSummary {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly experienceMode: "live";
  readonly dataClass: "private";
  readonly runId: string;
  readonly portfolioName: string;
  readonly owner: IdentitySummary;
  readonly state: RunState;
  readonly sources: readonly LiveSourceProgress[];
  readonly portfolioPlanDigest?: string;
  readonly updatedAt: string;
}

export interface ListLiveRunsResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly runs: readonly LiveRunSummary[];
}

export interface CreateLiveRunRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly portfolioName: string;
  readonly cloudSetupId: string;
  /** Exactly jde, dynamics, and ebs, each once. */
  readonly sources: readonly [SourceId, SourceId, SourceId];
}

export interface LiveSourceProgress {
  readonly sourceId: SourceId;
  readonly hostname: SourceReplay["hostname"];
  readonly state: RunState;
  readonly recordsRead: number;
  readonly recordsWritten: number;
  readonly recordsRejected: number;
  readonly planDigest?: string;
  readonly failureCode?: string;
  readonly evidenceReferences: readonly EvidenceReference[];
}

export interface LiveSourceResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly experienceMode: "live";
  readonly dataClass: "private";
  readonly runId: string;
  readonly state: RunState;
  readonly sourceId: SourceId;
  readonly hostname: SourceReplay["hostname"];
  readonly snapshotVersion: number;
  readonly updatedAt: string;
  readonly progress: LiveSourceProgress;
  readonly detail?: SourceReplay;
}

export interface LiveRunEvent {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly eventId: string;
  readonly runId: string;
  readonly sequence: number;
  readonly timestamp: string;
  readonly sourceId?: SourceId;
  readonly eventType: string;
  readonly state: RunState;
  readonly summary: string;
  readonly evidenceReferences: readonly EvidenceReference[];
}

export interface TerminalFrame {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly frameId: string;
  readonly runId: string;
  readonly sourceId: SourceId;
  readonly globalSequence: number;
  readonly laneSequence: number;
  readonly timestamp: string;
  readonly lane: TerminalLane;
  readonly stream: TerminalStream;
  readonly producer: string;
  readonly tool: string;
  readonly line: string;
  readonly severity: TerminalSeverity;
  readonly evidenceReferences: readonly EvidenceReference[];
}

/** Actor is deliberately absent; the BFF derives it from verified claims. */
export interface LiveApprovalRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly planDigest: string;
  readonly decision: "approve" | "reject";
  readonly reason?: string;
}

export interface LiveApprovalResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly runId: string;
  readonly approvalId: string;
  readonly planDigest: string;
  readonly decision: "approve" | "reject";
  readonly resultingState: "approved" | "cancelled";
  readonly decidedAt: string;
}

export interface CloudSetupRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly projectId: string;
  readonly region: string;
  readonly datasetPrefix: string;
}

export interface CloudConnectionResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly status: "not_connected" | "pending" | "verified" | "degraded";
  readonly setupId?: string;
  readonly projectId?: string;
  readonly region?: string;
  readonly datasetPrefix?: string;
  readonly verifiedAt?: string;
  readonly missingCapabilities?: readonly string[];
}

export interface CloudSetupResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly setupId: string;
  readonly projectId: string;
  readonly region: string;
  readonly command: string;
  readonly commandDigest: string;
  readonly expiresAt: string;
}

export interface CloudVerifyRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly setupId: string;
  readonly receipt: string;
}

export interface CloudVerifyResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly setupId: string;
  readonly status: "verified" | "incomplete";
  readonly projectId: string;
  readonly region: string;
  readonly verifiedAt: string;
  readonly missingCapabilities?: readonly string[];
}

export interface DriverResearchRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly projectId: string;
  readonly databaseFamily: string;
  readonly databaseVersion: string;
  readonly applicationLayer: string;
  readonly javaRuntime: string;
  readonly connectivityMode: "tailscale" | "private_service_connect" | "vpn";
  readonly officialRepository?: string;
}

export interface DriverCandidate {
  readonly candidateId: string;
  readonly coordinates: string;
  readonly version: string;
  readonly officialSource: string;
  readonly compatibility: string;
  readonly license: string;
  readonly redistribution: "allowed" | "restricted" | "unknown";
  readonly checksumAvailable: boolean;
  readonly signatureAvailable: boolean;
  readonly confidence: number;
  readonly caveats: readonly string[];
}

export interface DriverResearchResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly researchId: string;
  readonly model: string;
  readonly projectId: string;
  readonly createdAt: string;
  readonly candidates: readonly DriverCandidate[];
  readonly evidenceDigest: string;
}

export interface DriverResearchAccepted {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly researchId: string;
  readonly status: "queued";
  readonly statusLocation: string;
  readonly createdAt: string;
}

export interface DriverResearchStatusResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly researchId: string;
  readonly status: "queued" | "running" | "completed" | "failed";
  readonly updatedAt: string;
  readonly result?: DriverResearchResponse;
  readonly failureCode?: string;
}

export interface DriverApprovalRequest {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly researchId: string;
  readonly candidateId: string;
  readonly evidenceDigest: string;
}

export interface DriverApprovalResponse {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly researchId: string;
  readonly candidateId: string;
  readonly status: "pending_upload" | "retrieving" | "verified";
  readonly approvedAt: string;
  readonly artifactFingerprint?: string;
  readonly retrievalMode: "artifact_registry_remote" | "manual_vendor_upload";
}

export interface ProblemDetails {
  readonly schemaVersion: typeof WEB_SCHEMA_VERSION;
  readonly type: string;
  readonly title: string;
  readonly status: number;
  readonly detail?: string;
  readonly requestId?: string;
}

/** Practice approval is replay-local state and is never sent to the BFF. */
export interface PracticeApprovalDecision {
  readonly decision: "approve" | "reject";
  readonly planDigest: string;
  readonly decidedAt: string;
}
