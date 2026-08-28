package main

// Generated-style Go snapshot of contracts/web/v1. These additive browser BFF
// types intentionally do not alias or modify the frozen internal /api/v1 types.

const WebSchemaVersion = "1.0.0"
const WebRequirementsSHA256 = "37374d4fb13c4fd890e60c07b7d691fec0fe34ac5440b878aa275e5d9f3c0191"

type ExperienceMode string

const (
	ExperienceModeRecordedDemo ExperienceMode = "recorded_demo"
	ExperienceModeLive         ExperienceMode = "live"
)

type DataClass string

const (
	DataClassSyntheticDemo DataClass = "synthetic_demo"
	DataClassPrivate       DataClass = "private"
)

type WebSourceID string
type WebRunState string
type WebEvidenceKind string
type WebTerminalLane string
type WebTerminalStream string
type WebTerminalSeverity string

type WebNamedValue struct {
	Name     string `json:"name"`
	DataType string `json:"dataType"`
	Value    any    `json:"value"`
}

type WebSchemaField struct {
	Name        string `json:"name"`
	DataType    string `json:"dataType"`
	Nullable    bool   `json:"nullable"`
	Description string `json:"description,omitempty"`
}

type WebEvidenceReference struct {
	ArtifactID string          `json:"artifactId"`
	Kind       WebEvidenceKind `json:"kind"`
	Digest     string          `json:"digest"`
}

type WebReconciliation struct {
	Status              string               `json:"status"`
	RecordsRead         int64                `json:"recordsRead"`
	RecordsWritten      int64                `json:"recordsWritten"`
	RecordsRejected     int64                `json:"recordsRejected"`
	OutputRows          int64                `json:"outputRows"`
	SourceChecksum      string               `json:"sourceChecksum"`
	DestinationChecksum string               `json:"destinationChecksum"`
	Evidence            WebEvidenceReference `json:"evidence"`
}

type WebSourceSample struct {
	RecordID      string          `json:"recordId"`
	RawBytesHex   string          `json:"rawBytesHex"`
	DecodedFields []WebNamedValue `json:"decodedFields"`
}

type WebSourceSystemReplay struct {
	DatabaseFamily   string            `json:"databaseFamily"`
	DatabaseVersion  string            `json:"databaseVersion"`
	ApplicationLayer string            `json:"applicationLayer"`
	Schema           []WebSchemaField  `json:"schema"`
	Samples          []WebSourceSample `json:"samples"`
	ExampleQueries   []string          `json:"exampleQueries"`
}

type WebCompilerAction struct {
	Sequence           int64                  `json:"sequence"`
	EventID            string                 `json:"eventId"`
	Timestamp          string                 `json:"timestamp"`
	Stage              string                 `json:"stage"`
	Agent              string                 `json:"agent"`
	Tool               string                 `json:"tool"`
	Summary            string                 `json:"summary"`
	Result             string                 `json:"result"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

type WebDeclarativeTransform struct {
	Sequence    int64  `json:"sequence"`
	Operation   string `json:"operation"`
	SourceField string `json:"sourceField"`
	TargetField string `json:"targetField"`
	Encoding    string `json:"encoding,omitempty"`
	TargetType  string `json:"targetType,omitempty"`
	Format      string `json:"format,omitempty"`
}

type WebDriverArtifact struct {
	Coordinates       string `json:"coordinates"`
	Version           string `json:"version"`
	SourceURL         string `json:"sourceUrl"`
	License           string `json:"license"`
	SHA256            string `json:"sha256"`
	SignatureVerified bool   `json:"signatureVerified"`
}

type WebRecordedApproval struct {
	ApprovalID string `json:"approvalId"`
	Decision   string `json:"decision"`
	DecidedAt  string `json:"decidedAt"`
	PlanDigest string `json:"planDigest"`
}

type WebCompilerReplay struct {
	Actions              []WebCompilerAction       `json:"actions"`
	Transforms           []WebDeclarativeTransform `json:"transforms"`
	Driver               WebDriverArtifact         `json:"driver"`
	LocalGemmaEvidence   WebEvidenceReference      `json:"localGemmaEvidence"`
	GeminiVertexEvidence WebEvidenceReference      `json:"geminiVertexEvidence"`
	BeamTransformIDs     []string                  `json:"beamTransformIds"`
	DataflowJobID        string                    `json:"dataflowJobId"`
	Approval             WebRecordedApproval       `json:"approval"`
}

type WebDestinationRow struct {
	RecordID string          `json:"recordId"`
	Fields   []WebNamedValue `json:"fields"`
}

type WebDestinationReplay struct {
	Dataset          string               `json:"dataset"`
	Table            string               `json:"table"`
	Schema           []WebSchemaField     `json:"schema"`
	Rows             []WebDestinationRow  `json:"rows"`
	Reconciliation   WebReconciliation    `json:"reconciliation"`
	DataflowEvidence WebEvidenceReference `json:"dataflowEvidence"`
	BigQueryEvidence WebEvidenceReference `json:"bigQueryEvidence"`
	SuggestedQueries []string             `json:"suggestedQueries"`
}

type WebSourceReplay struct {
	SourceID       WebSourceID           `json:"sourceId"`
	Hostname       string                `json:"hostname"`
	DisplayName    string                `json:"displayName"`
	Source         WebSourceSystemReplay `json:"source"`
	Compiler       WebCompilerReplay     `json:"compiler"`
	Destination    WebDestinationReplay  `json:"destination"`
	TerminalFrames []WebTerminalFrame    `json:"terminalFrames"`
}

type WebReplayEvent struct {
	Sequence           int64                  `json:"sequence"`
	EventID            string                 `json:"eventId"`
	Timestamp          string                 `json:"timestamp"`
	SourceID           WebSourceID            `json:"sourceId,omitempty"`
	EventType          string                 `json:"eventType"`
	State              WebRunState            `json:"state"`
	Summary            string                 `json:"summary"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

type WebPracticeApproval struct {
	PauseAfterSequence int64  `json:"pauseAfterSequence"`
	PlanDigest         string `json:"planDigest"`
	Prompt             string `json:"prompt"`
}

// DemoManifest is content-addressed and immutable after successful publication.
type DemoManifest struct {
	SchemaVersion       string                 `json:"schemaVersion"`
	DemoID              string                 `json:"demoId"`
	ExperienceMode      ExperienceMode         `json:"experienceMode"`
	DataClass           DataClass              `json:"dataClass"`
	Title               string                 `json:"title"`
	SourceRunID         string                 `json:"sourceRunId"`
	RunState            WebRunState            `json:"runState"`
	PortfolioPlanDigest string                 `json:"portfolioPlanDigest"`
	PublishedAt         string                 `json:"publishedAt"`
	BundleDigest        string                 `json:"bundleDigest"`
	PracticeApproval    WebPracticeApproval    `json:"practiceApproval"`
	Sources             []WebSourceReplay      `json:"sources"`
	Events              []WebReplayEvent       `json:"events"`
	Evidence            []WebEvidenceReference `json:"evidence"`
	Reconciliation      WebReconciliation      `json:"reconciliation"`
}

type WebDemoSummary struct {
	SchemaVersion string `json:"schemaVersion"`
	DemoID        string `json:"demoId"`
	Title         string `json:"title"`
	SourceRunID   string `json:"sourceRunId"`
	PublishedAt   string `json:"publishedAt"`
	BundleDigest  string `json:"bundleDigest"`
}

type WebIdentitySummary struct {
	Subject     string `json:"subject"`
	DisplayName string `json:"displayName"`
	Email       string `json:"email"`
	PictureURL  string `json:"pictureUrl,omitempty"`
}

type WebSessionResponse struct {
	SchemaVersion string             `json:"schemaVersion"`
	Authenticated bool               `json:"authenticated"`
	User          WebIdentitySummary `json:"user"`
}

type WebListDemosResponse struct {
	SchemaVersion string           `json:"schemaVersion"`
	Demos         []WebDemoSummary `json:"demos"`
}

type WebPublishDemoRequest struct {
	SchemaVersion string       `json:"schemaVersion"`
	Manifest      DemoManifest `json:"manifest"`
}

type WebPublishDemoResponse struct {
	SchemaVersion string `json:"schemaVersion"`
	DemoID        string `json:"demoId"`
	PublishedAt   string `json:"publishedAt"`
	BundleDigest  string `json:"bundleDigest"`
	Location      string `json:"location"`
}

type WebLiveRunSummary struct {
	SchemaVersion       string                  `json:"schemaVersion"`
	ExperienceMode      ExperienceMode          `json:"experienceMode"`
	DataClass           DataClass               `json:"dataClass"`
	RunID               string                  `json:"runId"`
	PortfolioName       string                  `json:"portfolioName"`
	Owner               WebIdentitySummary      `json:"owner"`
	State               WebRunState             `json:"state"`
	Sources             []WebLiveSourceProgress `json:"sources"`
	PortfolioPlanDigest string                  `json:"portfolioPlanDigest,omitempty"`
	UpdatedAt           string                  `json:"updatedAt"`
}

type WebListLiveRunsResponse struct {
	SchemaVersion string              `json:"schemaVersion"`
	Runs          []WebLiveRunSummary `json:"runs"`
}

type WebCreateLiveRunRequest struct {
	SchemaVersion string        `json:"schemaVersion"`
	PortfolioName string        `json:"portfolioName"`
	CloudSetupID  string        `json:"cloudSetupId"`
	Sources       []WebSourceID `json:"sources"`
}

type WebLiveSourceProgress struct {
	SourceID           WebSourceID            `json:"sourceId"`
	Hostname           string                 `json:"hostname"`
	State              WebRunState            `json:"state"`
	RecordsRead        int64                  `json:"recordsRead"`
	RecordsWritten     int64                  `json:"recordsWritten"`
	RecordsRejected    int64                  `json:"recordsRejected"`
	PlanDigest         string                 `json:"planDigest,omitempty"`
	FailureCode        string                 `json:"failureCode,omitempty"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

type WebLiveSourceResponse struct {
	SchemaVersion   string                `json:"schemaVersion"`
	ExperienceMode  ExperienceMode        `json:"experienceMode"`
	DataClass       DataClass             `json:"dataClass"`
	RunID           string                `json:"runId"`
	State           WebRunState           `json:"state"`
	SourceID        WebSourceID           `json:"sourceId"`
	Hostname        string                `json:"hostname"`
	SnapshotVersion int64                 `json:"snapshotVersion"`
	UpdatedAt       string                `json:"updatedAt"`
	Progress        WebLiveSourceProgress `json:"progress"`
	Detail          *WebSourceReplay      `json:"detail,omitempty"`
}

type WebLiveRunEvent struct {
	SchemaVersion      string                 `json:"schemaVersion"`
	EventID            string                 `json:"eventId"`
	RunID              string                 `json:"runId"`
	Sequence           int64                  `json:"sequence"`
	Timestamp          string                 `json:"timestamp"`
	SourceID           WebSourceID            `json:"sourceId,omitempty"`
	EventType          string                 `json:"eventType"`
	State              WebRunState            `json:"state"`
	Summary            string                 `json:"summary"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

type WebTerminalFrame struct {
	SchemaVersion      string                 `json:"schemaVersion"`
	FrameID            string                 `json:"frameId"`
	RunID              string                 `json:"runId"`
	SourceID           WebSourceID            `json:"sourceId"`
	GlobalSequence     int64                  `json:"globalSequence"`
	LaneSequence       int64                  `json:"laneSequence"`
	Timestamp          string                 `json:"timestamp"`
	Lane               WebTerminalLane        `json:"lane"`
	Stream             WebTerminalStream      `json:"stream"`
	Producer           string                 `json:"producer"`
	Tool               string                 `json:"tool"`
	Line               string                 `json:"line"`
	Severity           WebTerminalSeverity    `json:"severity"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

// WebLiveApprovalRequest omits an actor by design; verified claims supply it.
type WebLiveApprovalRequest struct {
	SchemaVersion string `json:"schemaVersion"`
	PlanDigest    string `json:"planDigest"`
	Decision      string `json:"decision"`
	Reason        string `json:"reason,omitempty"`
}

type WebLiveApprovalResponse struct {
	SchemaVersion  string `json:"schemaVersion"`
	RunID          string `json:"runId"`
	ApprovalID     string `json:"approvalId"`
	PlanDigest     string `json:"planDigest"`
	Decision       string `json:"decision"`
	ResultingState string `json:"resultingState"`
	DecidedAt      string `json:"decidedAt"`
}

type WebCloudSetupRequest struct {
	SchemaVersion string `json:"schemaVersion"`
	ProjectID     string `json:"projectId"`
	Region        string `json:"region"`
	DatasetPrefix string `json:"datasetPrefix"`
}

type WebCloudConnectionResponse struct {
	SchemaVersion       string   `json:"schemaVersion"`
	Status              string   `json:"status"`
	SetupID             string   `json:"setupId,omitempty"`
	ProjectID           string   `json:"projectId,omitempty"`
	Region              string   `json:"region,omitempty"`
	DatasetPrefix       string   `json:"datasetPrefix,omitempty"`
	VerifiedAt          string   `json:"verifiedAt,omitempty"`
	MissingCapabilities []string `json:"missingCapabilities,omitempty"`
}

type WebCloudSetupResponse struct {
	SchemaVersion string `json:"schemaVersion"`
	SetupID       string `json:"setupId"`
	ProjectID     string `json:"projectId"`
	Region        string `json:"region"`
	Command       string `json:"command"`
	CommandDigest string `json:"commandDigest"`
	ExpiresAt     string `json:"expiresAt"`
}

type WebCloudVerifyRequest struct {
	SchemaVersion string `json:"schemaVersion"`
	SetupID       string `json:"setupId"`
	Receipt       string `json:"receipt"`
}

type WebCloudVerifyResponse struct {
	SchemaVersion       string   `json:"schemaVersion"`
	SetupID             string   `json:"setupId"`
	Status              string   `json:"status"`
	ProjectID           string   `json:"projectId"`
	Region              string   `json:"region"`
	VerifiedAt          string   `json:"verifiedAt"`
	MissingCapabilities []string `json:"missingCapabilities,omitempty"`
}

type WebDriverResearchRequest struct {
	SchemaVersion      string `json:"schemaVersion"`
	ProjectID          string `json:"projectId"`
	DatabaseFamily     string `json:"databaseFamily"`
	DatabaseVersion    string `json:"databaseVersion"`
	ApplicationLayer   string `json:"applicationLayer"`
	JavaRuntime        string `json:"javaRuntime"`
	ConnectivityMode   string `json:"connectivityMode"`
	OfficialRepository string `json:"officialRepository,omitempty"`
}

type WebDriverCandidate struct {
	CandidateID        string   `json:"candidateId"`
	Coordinates        string   `json:"coordinates"`
	Version            string   `json:"version"`
	OfficialSource     string   `json:"officialSource"`
	Compatibility      string   `json:"compatibility"`
	License            string   `json:"license"`
	Redistribution     string   `json:"redistribution"`
	ChecksumAvailable  bool     `json:"checksumAvailable"`
	SignatureAvailable bool     `json:"signatureAvailable"`
	Confidence         float64  `json:"confidence"`
	Caveats            []string `json:"caveats"`
}

type WebDriverResearchResponse struct {
	SchemaVersion  string               `json:"schemaVersion"`
	ResearchID     string               `json:"researchId"`
	Model          string               `json:"model"`
	ProjectID      string               `json:"projectId"`
	CreatedAt      string               `json:"createdAt"`
	Candidates     []WebDriverCandidate `json:"candidates"`
	EvidenceDigest string               `json:"evidenceDigest"`
}

type WebDriverResearchAccepted struct {
	SchemaVersion  string `json:"schemaVersion"`
	ResearchID     string `json:"researchId"`
	Status         string `json:"status"`
	StatusLocation string `json:"statusLocation"`
	CreatedAt      string `json:"createdAt"`
}

type WebDriverResearchStatusResponse struct {
	SchemaVersion string                     `json:"schemaVersion"`
	ResearchID    string                     `json:"researchId"`
	Status        string                     `json:"status"`
	UpdatedAt     string                     `json:"updatedAt"`
	Result        *WebDriverResearchResponse `json:"result,omitempty"`
	FailureCode   string                     `json:"failureCode,omitempty"`
}

type WebDriverApprovalRequest struct {
	SchemaVersion  string `json:"schemaVersion"`
	ResearchID     string `json:"researchId"`
	CandidateID    string `json:"candidateId"`
	EvidenceDigest string `json:"evidenceDigest"`
}

type WebDriverApprovalResponse struct {
	SchemaVersion       string `json:"schemaVersion"`
	ResearchID          string `json:"researchId"`
	CandidateID         string `json:"candidateId"`
	Status              string `json:"status"`
	ApprovedAt          string `json:"approvedAt"`
	ArtifactFingerprint string `json:"artifactFingerprint,omitempty"`
	RetrievalMode       string `json:"retrievalMode"`
}

type WebProblemDetails struct {
	SchemaVersion string `json:"schemaVersion"`
	Type          string `json:"type"`
	Title         string `json:"title"`
	Status        int    `json:"status"`
	Detail        string `json:"detail,omitempty"`
	RequestID     string `json:"requestId,omitempty"`
}
