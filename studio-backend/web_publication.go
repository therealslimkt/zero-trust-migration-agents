package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

var (
	webDigestPattern   = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)
	webRunIDPattern    = regexp.MustCompile(`^mig_[A-Za-z0-9]{12,64}$`)
	webDemoIDPattern   = regexp.MustCompile(`^demo_[A-Za-z0-9_-]{8,64}$`)
	webArtifactPattern = regexp.MustCompile(`^art_[A-Za-z0-9._-]{8,128}$`)
	webEventPattern    = regexp.MustCompile(`^evt_[A-Za-z0-9]{12,64}$`)
	webHexPattern      = regexp.MustCompile(`^(?:[a-fA-F0-9]{2})+$`)

	webCredentialValuePatterns = []*regexp.Regexp{
		regexp.MustCompile(`(?i)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----`),
		regexp.MustCompile(`(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}`),
		regexp.MustCompile(`\bAIza[0-9A-Za-z_-]{30,}\b`),
		regexp.MustCompile(`\bAKIA[0-9A-Z]{16}\b`),
		regexp.MustCompile(`\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b`),
		regexp.MustCompile(`\bya29\.[0-9A-Za-z_-]{20,}\b`),
		regexp.MustCompile(`\beyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\b`),
		regexp.MustCompile(`://[^/\s:@]+:[^/\s@]+@`),
	}
)

var webCredentialKeys = map[string]struct{}{
	"accesstoken": {}, "accesstokenvalue": {}, "apikey": {}, "authorization": {},
	"clientsecret": {}, "credential": {}, "credentials": {}, "idtoken": {},
	"password": {}, "passwd": {}, "privatekey": {}, "privatekeyid": {},
	"refreshtoken": {}, "secret": {}, "secretkey": {}, "serviceaccountkey": {},
}

var webCanonicalSourceHostnames = map[WebSourceID]string{
	"jde": "legacy-jde-db", "dynamics": "dynamics-ax", "ebs": "oracle-ebs-19c",
}

var webSourceScopedEventTypes = map[string]bool{
	"source.inventory.started": true, "source.inventory.completed": true,
	"source.redaction.completed": true, "source.plan.ready": true,
	"source.execution.started": true, "source.execution.completed": true,
	"source.verification.completed": true, "source.failed": true,
	"migration.created": false, "portfolio.awaiting_approval": false,
	"portfolio.approved": false, "portfolio.rejected": false,
	"migration.completed": false, "migration.failed": false, "migration.cancelled": false,
}

var webRequiredEvidenceKinds = []WebEvidenceKind{
	"source_manifest", "redaction_report", "transform_plan", "dataflow_job",
	"bigquery_table", "reconciliation", "audit_log",
}

// WebPublicationValidationError reports stable machine-readable rejection
// codes. Details never contain manifest values, which prevents credential
// material from being reflected through an error path.
type WebPublicationValidationError struct {
	Codes []string
}

func (e *WebPublicationValidationError) Error() string {
	return "demo manifest rejected: " + strings.Join(e.Codes, ", ")
}

// CanonicalDemoManifestJSON returns the exact digest payload: compact UTF-8
// JSON, lexicographically sorted object keys, array order preserved, and the
// root bundleDigest member omitted. It never mutates the caller's manifest.
func CanonicalDemoManifestJSON(manifest DemoManifest) ([]byte, error) {
	encoded, err := json.Marshal(manifest)
	if err != nil {
		return nil, fmt.Errorf("encode manifest: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(encoded))
	decoder.UseNumber()
	var document map[string]any
	if err := decoder.Decode(&document); err != nil {
		return nil, fmt.Errorf("decode manifest for canonicalization: %w", err)
	}
	delete(document, "bundleDigest")
	var canonical bytes.Buffer
	if err := writeWebCanonicalJSON(&canonical, document); err != nil {
		return nil, err
	}
	return canonical.Bytes(), nil
}

// DemoManifestDigest computes the content address expected in bundleDigest.
func DemoManifestDigest(manifest DemoManifest) (string, error) {
	canonical, err := CanonicalDemoManifestJSON(manifest)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(canonical)
	return "sha256:" + hex.EncodeToString(digest[:]), nil
}

// ValidateDemoManifestForPublication enforces the public replay publication
// gate. It rejects private/non-synthetic, non-completed, unreconciled,
// credential-bearing, referentially incomplete, or incorrectly addressed
// bundles.
func ValidateDemoManifestForPublication(manifest DemoManifest) error {
	validator := webManifestValidator{
		evidenceByID:             make(map[string]WebEvidenceReference),
		eventIDs:                 make(map[string]struct{}),
		terminalFrameIDs:         make(map[string]struct{}),
		terminalFramesBySequence: make(map[int64]WebTerminalFrame),
	}
	validator.validate(manifest)
	if len(validator.codes) == 0 {
		return nil
	}
	return &WebPublicationValidationError{Codes: validator.codes}
}

type webManifestValidator struct {
	codes                    []string
	evidenceByID             map[string]WebEvidenceReference
	eventIDs                 map[string]struct{}
	terminalFrameIDs         map[string]struct{}
	terminalFramesBySequence map[int64]WebTerminalFrame
}

func (v *webManifestValidator) add(code string) {
	for _, existing := range v.codes {
		if existing == code {
			return
		}
	}
	v.codes = append(v.codes, code)
}

func (v *webManifestValidator) validate(manifest DemoManifest) {
	if manifest.SchemaVersion != WebSchemaVersion {
		v.add("schema_version_invalid")
	}
	if manifest.ExperienceMode != ExperienceModeRecordedDemo {
		v.add("experience_mode_not_recorded_demo")
	}
	if manifest.DataClass != DataClassSyntheticDemo {
		v.add("data_class_not_synthetic_demo")
	}
	if manifest.RunState != "completed" {
		v.add("run_not_completed")
	}
	if !webDemoIDPattern.MatchString(manifest.DemoID) || !webRunIDPattern.MatchString(manifest.SourceRunID) {
		v.add("identifier_invalid")
	}
	if !safeWebPublicText(manifest.Title) || !validWebDigest(manifest.PortfolioPlanDigest) {
		v.add("manifest_identity_invalid")
	}
	if _, err := time.Parse(time.RFC3339, manifest.PublishedAt); err != nil {
		v.add("published_at_invalid")
	}

	v.validateEvidenceCatalog(manifest.Evidence)
	v.validateSources(manifest)
	v.validateEvents(manifest)
	v.validateReconciliation(manifest.Reconciliation, "portfolio_reconciliation_invalid")

	if manifest.PracticeApproval.PlanDigest != manifest.PortfolioPlanDigest {
		v.add("practice_approval_digest_mismatch")
	}
	if !safeWebPublicText(manifest.PracticeApproval.Prompt) {
		v.add("practice_approval_invalid")
	}

	encoded, err := json.Marshal(manifest)
	if err != nil {
		v.add("manifest_not_json_serializable")
	} else {
		var document any
		decoder := json.NewDecoder(bytes.NewReader(encoded))
		decoder.UseNumber()
		if err := decoder.Decode(&document); err != nil || containsWebCredential(document) {
			v.add("credential_material_present")
		}
	}

	digest, err := DemoManifestDigest(manifest)
	if err != nil || !validWebDigest(manifest.BundleDigest) || digest != manifest.BundleDigest {
		v.add("bundle_digest_mismatch")
	}
}

func (v *webManifestValidator) validateEvidenceCatalog(evidence []WebEvidenceReference) {
	if len(evidence) == 0 {
		v.add("evidence_missing")
		return
	}
	kinds := make(map[WebEvidenceKind]bool)
	for _, reference := range evidence {
		if !webArtifactPattern.MatchString(reference.ArtifactID) || !validWebDigest(reference.Digest) {
			v.add("evidence_invalid")
		}
		if _, duplicate := v.evidenceByID[reference.ArtifactID]; duplicate {
			v.add("evidence_duplicate")
		} else {
			v.evidenceByID[reference.ArtifactID] = reference
		}
		kinds[reference.Kind] = true
	}
	for _, kind := range webRequiredEvidenceKinds {
		if !kinds[kind] {
			v.add("required_evidence_missing")
		}
	}
}

func (v *webManifestValidator) validateSources(manifest DemoManifest) {
	if len(manifest.Sources) != len(webCanonicalSourceHostnames) {
		v.add("source_set_invalid")
	}
	seen := make(map[WebSourceID]bool)
	var aggregateRead, aggregateWritten, aggregateRejected int64
	for _, source := range manifest.Sources {
		expectedHostname, known := webCanonicalSourceHostnames[source.SourceID]
		if !known || seen[source.SourceID] || source.Hostname != expectedHostname {
			v.add("source_set_invalid")
		}
		seen[source.SourceID] = true
		if !safeWebPublicText(source.DisplayName) || !safeWebPublicText(source.Source.DatabaseFamily) ||
			!safeWebPublicText(source.Source.DatabaseVersion) || !safeWebPublicText(source.Source.ApplicationLayer) ||
			len(source.Source.Schema) == 0 || len(source.Source.Samples) == 0 || len(source.Source.ExampleQueries) == 0 {
			v.add("source_detail_incomplete")
		}
		for _, sample := range source.Source.Samples {
			if sample.RecordID == "" || !webHexPattern.MatchString(sample.RawBytesHex) || len(sample.DecodedFields) == 0 {
				v.add("source_sample_invalid")
			}
			if raw, err := hex.DecodeString(sample.RawBytesHex); err != nil || containsWebCredential(string(raw)) {
				v.add("credential_material_present")
			}
		}
		if len(source.Compiler.Actions) == 0 || len(source.Compiler.Transforms) == 0 || len(source.Compiler.BeamTransformIDs) == 0 || source.Compiler.DataflowJobID == "" {
			v.add("compiler_detail_incomplete")
		}
		sourceEvidenceKinds := make(map[WebEvidenceKind]bool)
		if source.Compiler.Approval.Decision != "approved" || source.Compiler.Approval.PlanDigest != manifest.PortfolioPlanDigest {
			v.add("recorded_approval_invalid")
		}
		if _, err := time.Parse(time.RFC3339, source.Compiler.Approval.DecidedAt); err != nil {
			v.add("recorded_approval_invalid")
		}
		v.validateReference(source.Compiler.LocalGemmaEvidence)
		v.validateReference(source.Compiler.GeminiVertexEvidence)
		if source.Compiler.LocalGemmaEvidence.Kind != "redaction_report" || source.Compiler.GeminiVertexEvidence.Kind != "transform_plan" {
			v.add("compiler_evidence_role_invalid")
		}
		sourceEvidenceKinds[source.Compiler.LocalGemmaEvidence.Kind] = true
		sourceEvidenceKinds[source.Compiler.GeminiVertexEvidence.Kind] = true
		var previousActionTimestamp time.Time
		for actionIndex, action := range source.Compiler.Actions {
			if action.Sequence != int64(actionIndex+1) || !webEventPattern.MatchString(action.EventID) ||
				!safeWebPublicText(action.Agent) || !safeWebPublicText(action.Tool) ||
				!safeWebPublicText(action.Summary) || !safeWebPublicText(action.Result) {
				v.add("compiler_action_invalid")
			}
			actionTimestamp, err := time.Parse(time.RFC3339, action.Timestamp)
			if err != nil || (!previousActionTimestamp.IsZero() && actionTimestamp.Before(previousActionTimestamp)) {
				v.add("compiler_action_invalid")
			} else {
				previousActionTimestamp = actionTimestamp
			}
			for _, reference := range action.EvidenceReferences {
				v.validateReference(reference)
				sourceEvidenceKinds[reference.Kind] = true
			}
		}
		for transformIndex, transform := range source.Compiler.Transforms {
			if transform.Sequence != int64(transformIndex+1) {
				v.add("transform_sequence_invalid")
			}
		}
		v.validateReconciliation(source.Destination.Reconciliation, "source_reconciliation_invalid")
		v.validateReference(source.Destination.Reconciliation.Evidence)
		v.validateReference(source.Destination.DataflowEvidence)
		v.validateReference(source.Destination.BigQueryEvidence)
		if source.Destination.DataflowEvidence.Kind != "dataflow_job" || source.Destination.BigQueryEvidence.Kind != "bigquery_table" {
			v.add("destination_evidence_role_invalid")
		}
		sourceEvidenceKinds[source.Destination.Reconciliation.Evidence.Kind] = true
		sourceEvidenceKinds[source.Destination.DataflowEvidence.Kind] = true
		sourceEvidenceKinds[source.Destination.BigQueryEvidence.Kind] = true
		for _, required := range []WebEvidenceKind{"source_manifest", "redaction_report", "transform_plan", "dataflow_job", "bigquery_table", "reconciliation"} {
			if !sourceEvidenceKinds[required] {
				v.add("source_required_evidence_missing")
			}
		}
		if len(source.Destination.Schema) == 0 || len(source.Destination.Rows) == 0 || len(source.Destination.SuggestedQueries) == 0 {
			v.add("destination_detail_incomplete")
		}
		v.validateTerminalFrames(manifest.SourceRunID, source)
		reconciliation := source.Destination.Reconciliation
		aggregateRead += reconciliation.RecordsRead
		aggregateWritten += reconciliation.RecordsWritten
		aggregateRejected += reconciliation.RecordsRejected
	}
	if len(seen) != len(webCanonicalSourceHostnames) {
		v.add("source_set_invalid")
	}
	v.validateTerminalTimeline()
	if manifest.Reconciliation.RecordsRead != aggregateRead ||
		manifest.Reconciliation.RecordsWritten != aggregateWritten ||
		manifest.Reconciliation.RecordsRejected != aggregateRejected ||
		manifest.Reconciliation.OutputRows != aggregateWritten {
		v.add("portfolio_reconciliation_invalid")
	}
}

func (v *webManifestValidator) validateTerminalFrames(runID string, source WebSourceReplay) {
	if len(source.TerminalFrames) < 1 || len(source.TerminalFrames) > webMaxSourceTerminalFrames {
		v.add("terminal_frames_missing")
		return
	}
	laneSequences := make(map[WebTerminalLane]int64)
	var previousGlobal int64
	var previousTimestamp time.Time
	for _, frame := range source.TerminalFrames {
		input := WebTerminalFrameAdmission{
			RunID: frame.RunID, SourceID: frame.SourceID, Timestamp: frame.Timestamp,
			Lane: frame.Lane, Stream: frame.Stream, Producer: frame.Producer, Tool: frame.Tool,
			Line: frame.Line, Severity: frame.Severity, EvidenceReferences: frame.EvidenceReferences,
		}
		if frame.SchemaVersion != WebSchemaVersion || !webTerminalFrameIDPattern.MatchString(frame.FrameID) {
			v.add("terminal_frame_invalid")
		}
		if suppressed, valid := webValidateTerminalAdmission(input); suppressed || !valid {
			v.add("terminal_frame_invalid")
		}
		if frame.RunID != runID || frame.SourceID != source.SourceID {
			v.add("terminal_frame_scope_invalid")
		}
		if frame.GlobalSequence <= previousGlobal {
			v.add("terminal_frame_sequence_invalid")
		}
		previousGlobal = frame.GlobalSequence
		laneSequences[frame.Lane]++
		if frame.LaneSequence != laneSequences[frame.Lane] {
			v.add("terminal_frame_sequence_invalid")
		}
		stamp, ok := cpParseStamp(frame.Timestamp)
		if !ok || (!previousTimestamp.IsZero() && stamp.Before(previousTimestamp)) {
			v.add("terminal_frame_timestamp_invalid")
		} else {
			previousTimestamp = stamp
		}
		if _, duplicate := v.terminalFrameIDs[frame.FrameID]; duplicate {
			v.add("terminal_frame_duplicate")
		}
		v.terminalFrameIDs[frame.FrameID] = struct{}{}
		if _, duplicate := v.terminalFramesBySequence[frame.GlobalSequence]; duplicate || frame.GlobalSequence < 1 {
			v.add("terminal_frame_sequence_invalid")
		} else {
			v.terminalFramesBySequence[frame.GlobalSequence] = frame
		}
		for _, reference := range frame.EvidenceReferences {
			v.validateReference(reference)
		}
	}
}

func (v *webManifestValidator) validateTerminalTimeline() {
	var previousTimestamp time.Time
	for sequence := int64(1); sequence <= int64(len(v.terminalFramesBySequence)); sequence++ {
		frame, ok := v.terminalFramesBySequence[sequence]
		if !ok {
			v.add("terminal_frame_sequence_invalid")
			continue
		}
		stamp, ok := cpParseStamp(frame.Timestamp)
		if !ok || (!previousTimestamp.IsZero() && stamp.Before(previousTimestamp)) {
			v.add("terminal_frame_timestamp_invalid")
			continue
		}
		previousTimestamp = stamp
	}
}

func (v *webManifestValidator) validateEvents(manifest DemoManifest) {
	if len(manifest.Events) == 0 {
		v.add("event_timeline_incomplete")
		return
	}
	approvalSeen := false
	completionSeen := false
	pauseSeen := false
	var previousTimestamp time.Time
	for index, event := range manifest.Events {
		if event.Sequence != int64(index+1) || !webEventPattern.MatchString(event.EventID) {
			v.add("event_sequence_invalid")
		}
		if !safeWebPublicText(event.Summary) {
			v.add("event_public_text_invalid")
		}
		if _, duplicate := v.eventIDs[event.EventID]; duplicate {
			v.add("event_duplicate")
		}
		v.eventIDs[event.EventID] = struct{}{}
		parsedTimestamp, err := time.Parse(time.RFC3339, event.Timestamp)
		if err != nil {
			v.add("event_timestamp_invalid")
		} else {
			if !previousTimestamp.IsZero() && parsedTimestamp.Before(previousTimestamp) {
				v.add("event_timestamp_not_monotonic")
			}
			previousTimestamp = parsedTimestamp
		}
		sourceScoped, knownType := webSourceScopedEventTypes[event.EventType]
		_, knownSource := webCanonicalSourceHostnames[event.SourceID]
		if !knownType || (sourceScoped && !knownSource) || (!sourceScoped && event.SourceID != "") {
			v.add("event_scope_invalid")
		}
		for _, reference := range event.EvidenceReferences {
			v.validateReference(reference)
		}
		if event.EventType == "portfolio.approved" {
			approvalSeen = true
		}
		if event.EventType == "migration.completed" && event.State == "completed" {
			completionSeen = true
		}
		if event.Sequence == manifest.PracticeApproval.PauseAfterSequence && event.EventType == "portfolio.awaiting_approval" {
			pauseSeen = true
		}
	}
	last := manifest.Events[len(manifest.Events)-1]
	first := manifest.Events[0]
	if first.EventType != "migration.created" || first.State != "created" || first.SourceID != "" ||
		!approvalSeen || !completionSeen || last.EventType != "migration.completed" || last.State != "completed" {
		v.add("event_timeline_incomplete")
	}
	if !pauseSeen {
		v.add("practice_approval_pause_invalid")
	}
}

func (v *webManifestValidator) validateReconciliation(reconciliation WebReconciliation, code string) {
	if reconciliation.Status != "matched" ||
		reconciliation.RecordsRead < 0 || reconciliation.RecordsWritten < 0 || reconciliation.RecordsRejected < 0 ||
		reconciliation.RecordsRead != reconciliation.RecordsWritten+reconciliation.RecordsRejected ||
		reconciliation.OutputRows != reconciliation.RecordsWritten ||
		!validWebDigest(reconciliation.SourceChecksum) ||
		reconciliation.SourceChecksum != reconciliation.DestinationChecksum ||
		reconciliation.Evidence.Kind != "reconciliation" {
		v.add(code)
	}
	v.validateReference(reconciliation.Evidence)
}

func (v *webManifestValidator) validateReference(reference WebEvidenceReference) {
	catalogued, ok := v.evidenceByID[reference.ArtifactID]
	if !ok || catalogued != reference {
		v.add("evidence_reference_unresolved")
	}
}

func validWebDigest(value string) bool {
	return webDigestPattern.MatchString(value)
}

func safeWebPublicText(value string) bool {
	if strings.TrimSpace(value) == "" || !utf8.ValidString(value) {
		return false
	}
	for _, r := range value {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}

func normalizeWebCredentialKey(key string) string {
	return strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9') {
			return r
		}
		return -1
	}, strings.ToLower(key))
}

func containsWebCredential(value any) bool {
	switch typed := value.(type) {
	case map[string]any:
		if fieldName, ok := typed["name"].(string); ok {
			if _, forbidden := webCredentialKeys[normalizeWebCredentialKey(fieldName)]; forbidden {
				return true
			}
		}
		for key, child := range typed {
			if _, forbidden := webCredentialKeys[normalizeWebCredentialKey(key)]; forbidden {
				return true
			}
			if containsWebCredential(child) {
				return true
			}
		}
	case []any:
		for _, child := range typed {
			if containsWebCredential(child) {
				return true
			}
		}
	case string:
		for _, pattern := range webCredentialValuePatterns {
			if pattern.MatchString(typed) {
				return true
			}
		}
	}
	return false
}

func writeWebCanonicalJSON(buffer *bytes.Buffer, value any) error {
	switch typed := value.(type) {
	case nil:
		buffer.WriteString("null")
	case bool:
		if typed {
			buffer.WriteString("true")
		} else {
			buffer.WriteString("false")
		}
	case json.Number:
		if _, err := strconv.ParseFloat(typed.String(), 64); err != nil {
			return fmt.Errorf("invalid JSON number")
		}
		buffer.WriteString(typed.String())
	case string:
		if !utf8.ValidString(typed) {
			return fmt.Errorf("canonical JSON contains invalid UTF-8")
		}
		writeWebCanonicalJSONString(buffer, typed)
	case []any:
		buffer.WriteByte('[')
		for index, child := range typed {
			if index > 0 {
				buffer.WriteByte(',')
			}
			if err := writeWebCanonicalJSON(buffer, child); err != nil {
				return err
			}
		}
		buffer.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(typed))
		for key := range typed {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		buffer.WriteByte('{')
		for index, key := range keys {
			if index > 0 {
				buffer.WriteByte(',')
			}
			writeWebCanonicalJSONString(buffer, key)
			buffer.WriteByte(':')
			if err := writeWebCanonicalJSON(buffer, typed[key]); err != nil {
				return err
			}
		}
		buffer.WriteByte('}')
	default:
		return fmt.Errorf("unsupported canonical JSON type %T", value)
	}
	return nil
}

func writeWebCanonicalJSONString(buffer *bytes.Buffer, value string) {
	const hexDigits = "0123456789abcdef"
	buffer.WriteByte('"')
	for _, r := range value {
		switch r {
		case '"', '\\':
			buffer.WriteByte('\\')
			buffer.WriteRune(r)
		case '\b':
			buffer.WriteString(`\b`)
		case '\f':
			buffer.WriteString(`\f`)
		case '\n':
			buffer.WriteString(`\n`)
		case '\r':
			buffer.WriteString(`\r`)
		case '\t':
			buffer.WriteString(`\t`)
		default:
			if r < 0x20 {
				buffer.WriteString(`\u00`)
				buffer.WriteByte(hexDigits[byte(r)>>4])
				buffer.WriteByte(hexDigits[byte(r)&0x0f])
			} else {
				buffer.WriteRune(r)
			}
		}
	}
	buffer.WriteByte('"')
}
