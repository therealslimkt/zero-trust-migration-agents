package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"strings"
	"testing"
)

func webTestDigest(hexDigit string) string {
	return "sha256:" + strings.Repeat(hexDigit, 64)
}

func webTestEvidence(id, kind, digit string) WebEvidenceReference {
	_ = digit
	body := webTestArtifactBody(id)
	digest := sha256.Sum256(body)
	return WebEvidenceReference{ArtifactID: id, Kind: WebEvidenceKind(kind), Digest: "sha256:" + hex.EncodeToString(digest[:])}
}

func webTestArtifactBody(id string) []byte {
	return []byte("immutable-artifact-body:" + id)
}

func webTestManifest(t *testing.T) DemoManifest {
	t.Helper()
	evidence := []WebEvidenceReference{
		webTestEvidence("art_source-manifest-01", "source_manifest", "1"),
		webTestEvidence("art_redaction-report-1", "redaction_report", "2"),
		webTestEvidence("art_transform-plan-001", "transform_plan", "3"),
		webTestEvidence("art_dataflow-job-0001", "dataflow_job", "4"),
		webTestEvidence("art_bigquery-table-01", "bigquery_table", "5"),
		webTestEvidence("art_reconciliation-01", "reconciliation", "6"),
		webTestEvidence("art_audit-log-000001", "audit_log", "7"),
	}
	reconciliation := func(digit string) WebReconciliation {
		return WebReconciliation{
			Status: "matched", RecordsRead: 1, RecordsWritten: 1, OutputRows: 1,
			SourceChecksum: webTestDigest(digit), DestinationChecksum: webTestDigest(digit),
			Evidence: evidence[5],
		}
	}
	source := func(id WebSourceID, hostname, displayName, rawHex, table, digit string) WebSourceReplay {
		return WebSourceReplay{
			SourceID: id, Hostname: hostname, DisplayName: displayName,
			Source: WebSourceSystemReplay{
				DatabaseFamily: string(id), DatabaseVersion: "demo-1", ApplicationLayer: displayName,
				Schema: []WebSchemaField{{Name: "customer_id", DataType: "STRING", Nullable: false}},
				Samples: []WebSourceSample{{
					RecordID: "synthetic-001", RawBytesHex: rawHex,
					DecodedFields: []WebNamedValue{
						{Name: "customer_id", DataType: "STRING", Value: "SYN-001"},
						{Name: "contact_email", DataType: "STRING", Value: "demo.person@example.test"},
					},
				}},
				ExampleQueries: []string{"SELECT customer_id FROM synthetic_customer"},
			},
			Compiler: WebCompilerReplay{
				Actions: []WebCompilerAction{{
					Sequence: 1, EventID: "evt_sourceaction0001", Timestamp: "2026-08-27T08:00:01Z",
					Stage: "protect", Agent: "local-gemma", Tool: "pii-redactor",
					Summary: "Protected the exact synthetic sample.", Result: "Deterministic checks passed.",
					EvidenceReferences: []WebEvidenceReference{evidence[0], evidence[1], evidence[2]},
				}},
				Transforms: []WebDeclarativeTransform{{Sequence: 1, Operation: "rename", SourceField: "CUST_ID", TargetField: "customer_id"}},
				Driver: WebDriverArtifact{
					Coordinates: "example:synthetic-driver:1.0", Version: "1.0",
					SourceURL: "https://repo.example.test/synthetic-driver", License: "Demo fixture",
					SHA256: webTestDigest("8"), SignatureVerified: true,
				},
				LocalGemmaEvidence: evidence[1], GeminiVertexEvidence: evidence[2],
				BeamTransformIDs: []string{"decode", "map", "write"}, DataflowJobID: "dataflow-demo-job-001",
				Approval: WebRecordedApproval{
					ApprovalID: "apr_recordedDemo001", Decision: "approved", DecidedAt: "2026-08-27T08:00:02Z",
					PlanDigest: webTestDigest("a"),
				},
			},
			Destination: WebDestinationReplay{
				Dataset: "legacy_migration", Table: table,
				Schema:         []WebSchemaField{{Name: "customer_id", DataType: "STRING", Nullable: false}},
				Rows:           []WebDestinationRow{{RecordID: "synthetic-001", Fields: []WebNamedValue{{Name: "customer_id", DataType: "STRING", Value: "SYN-001"}}}},
				Reconciliation: reconciliation(digit), DataflowEvidence: evidence[3], BigQueryEvidence: evidence[4],
				SuggestedQueries: []string{"SELECT * FROM legacy_migration." + table + " LIMIT 10"},
			},
		}
	}
	manifest := DemoManifest{
		SchemaVersion: WebSchemaVersion, DemoID: "demo_ownerapproved01",
		ExperienceMode: ExperienceModeRecordedDemo, DataClass: DataClassSyntheticDemo,
		Title: "Owner-approved three-source migration", SourceRunID: "mig_recordedDemo001",
		RunState: "completed", PortfolioPlanDigest: webTestDigest("a"), PublishedAt: "2026-08-27T08:05:00Z",
		PracticeApproval: WebPracticeApproval{
			PauseAfterSequence: 2, PlanDigest: webTestDigest("a"),
			Prompt: "Practice reviewing the exact recorded portfolio plan digest.",
		},
		Sources: []WebSourceReplay{
			source("jde", "legacy-jde-db", "JD Edwards World", "f1f2f3", "jde_f0101", "b"),
			source("maxdb", "legacy-maxdb", "SAP MaxDB", "414243", "sap_kna1", "c"),
			source("btrieve", "legacy-btrieve-db", "Sage Accpac", "010203", "accpac_arcus", "d"),
		},
		Events: []WebReplayEvent{
			{Sequence: 1, EventID: "evt_migrationcreated01", Timestamp: "2026-08-27T08:00:00Z", EventType: "migration.created", State: "created", Summary: "Recorded migration created.", EvidenceReferences: []WebEvidenceReference{}},
			{Sequence: 2, EventID: "evt_awaitapproval001", Timestamp: "2026-08-27T08:00:01Z", EventType: "portfolio.awaiting_approval", State: "awaiting_approval", Summary: "Recorded portfolio reached its approval gate.", EvidenceReferences: []WebEvidenceReference{evidence[2]}},
			{Sequence: 3, EventID: "evt_portapproved001", Timestamp: "2026-08-27T08:00:02Z", EventType: "portfolio.approved", State: "approved", Summary: "Recorded owner approval accepted.", EvidenceReferences: []WebEvidenceReference{evidence[6]}},
			{Sequence: 4, EventID: "evt_migcompleted001", Timestamp: "2026-08-27T08:05:00Z", EventType: "migration.completed", State: "completed", Summary: "Recorded migration completed and reconciled.", EvidenceReferences: []WebEvidenceReference{evidence[3], evidence[4], evidence[5], evidence[6]}},
		},
		Evidence: evidence,
		Reconciliation: WebReconciliation{
			Status: "matched", RecordsRead: 3, RecordsWritten: 3, OutputRows: 3,
			SourceChecksum: webTestDigest("e"), DestinationChecksum: webTestDigest("e"), Evidence: evidence[5],
		},
	}
	digest, err := DemoManifestDigest(manifest)
	if err != nil {
		t.Fatalf("DemoManifestDigest: %v", err)
	}
	manifest.BundleDigest = digest
	return manifest
}

func cloneWebTestManifest(t *testing.T, manifest DemoManifest) DemoManifest {
	t.Helper()
	encoded, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var clone DemoManifest
	if err := json.Unmarshal(encoded, &clone); err != nil {
		t.Fatal(err)
	}
	return clone
}

func webAssertPublicationCode(t *testing.T, err error, code string) {
	t.Helper()
	var validation *WebPublicationValidationError
	if !errors.As(err, &validation) {
		t.Fatalf("error = %v, want WebPublicationValidationError", err)
	}
	for _, actual := range validation.Codes {
		if actual == code {
			return
		}
	}
	t.Fatalf("validation codes = %v, want %q", validation.Codes, code)
}

func TestValidateDemoManifestForPublicationAcceptsCompleteSyntheticReplay(t *testing.T) {
	manifest := webTestManifest(t)
	if err := ValidateDemoManifestForPublication(manifest); err != nil {
		t.Fatalf("ValidateDemoManifestForPublication: %v", err)
	}
}

func TestDemoManifestDigestIsDeterministicAndOmitsOnlyItsOwnField(t *testing.T) {
	manifest := webTestManifest(t)
	first, err := DemoManifestDigest(manifest)
	if err != nil {
		t.Fatal(err)
	}
	const golden = "sha256:878f0e62200d375f2d2ab23b1579a21de4045fe8a835c8e993343714f7d2ae41"
	if first != golden {
		t.Fatalf("digest = %s, want golden %s", first, golden)
	}
	manifest.BundleDigest = webTestDigest("f")
	second, err := DemoManifestDigest(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatalf("digest changed with bundleDigest: %s != %s", first, second)
	}
	canonical, err := CanonicalDemoManifestJSON(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(canonical), "bundleDigest") {
		t.Fatal("canonical payload retained bundleDigest")
	}
	if !strings.HasPrefix(string(canonical), `{"dataClass":"synthetic_demo","demoId":`) {
		t.Fatalf("canonical object keys are not sorted: %.80s", canonical)
	}
}

func TestValidateDemoManifestForPublicationRejectsUnsafeOrUntruthfulBundles(t *testing.T) {
	base := webTestManifest(t)
	tests := []struct {
		name string
		code string
		edit func(*DemoManifest)
	}{
		{"private", "data_class_not_synthetic_demo", func(m *DemoManifest) { m.DataClass = DataClassPrivate }},
		{"live", "experience_mode_not_recorded_demo", func(m *DemoManifest) { m.ExperienceMode = ExperienceModeLive }},
		{"incomplete", "run_not_completed", func(m *DemoManifest) { m.RunState = "failed" }},
		{"unreconciled", "portfolio_reconciliation_invalid", func(m *DemoManifest) { m.Reconciliation.Status = "mismatched" }},
		{"missing evidence", "required_evidence_missing", func(m *DemoManifest) { m.Evidence = m.Evidence[:6] }},
		{"unresolved evidence", "evidence_reference_unresolved", func(m *DemoManifest) { m.Events[1].EvidenceReferences[0].Digest = webTestDigest("f") }},
		{"credential", "credential_material_present", func(m *DemoManifest) {
			m.Sources[0].Source.Samples[0].DecodedFields[0].Value = "Bearer abcdefghijklmnopqrstuvwxyz012345"
		}},
		{"credential field", "credential_material_present", func(m *DemoManifest) {
			m.Sources[0].Source.Samples[0].DecodedFields[0].Name = "password"
		}},
		{"wrong digest", "bundle_digest_mismatch", func(m *DemoManifest) { m.BundleDigest = webTestDigest("0") }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			manifest := cloneWebTestManifest(t, base)
			test.edit(&manifest)
			err := ValidateDemoManifestForPublication(manifest)
			if err == nil {
				t.Fatal("expected publication rejection")
			}
			webAssertPublicationCode(t, err, test.code)
		})
	}
}

func TestPublicationErrorsDoNotReflectCredentialMaterial(t *testing.T) {
	manifest := webTestManifest(t)
	secret := "Bearer super-secret-token-value-1234567890"
	manifest.Sources[0].Source.Samples[0].DecodedFields[0].Value = secret
	err := ValidateDemoManifestForPublication(manifest)
	webAssertPublicationCode(t, err, "credential_material_present")
	if strings.Contains(err.Error(), secret) {
		t.Fatal("publication error reflected credential material")
	}
}

func TestPublicationRejectsInvalidTimelineAndUnsafePublicText(t *testing.T) {
	base := webTestManifest(t)
	tests := []struct {
		name string
		code string
		edit func(*DemoManifest)
	}{
		{"first event", "event_timeline_incomplete", func(m *DemoManifest) { m.Events[0].EventType = "portfolio.approved" }},
		{"timestamp regression", "event_timestamp_not_monotonic", func(m *DemoManifest) { m.Events[2].Timestamp = "2026-08-27T07:00:00Z" }},
		{"source event without source", "event_scope_invalid", func(m *DemoManifest) { m.Events[0].EventType = "source.inventory.started" }},
		{"portfolio event with source", "event_scope_invalid", func(m *DemoManifest) { m.Events[1].SourceID = "jde" }},
		{"unsafe title", "manifest_identity_invalid", func(m *DemoManifest) { m.Title = "unsafe\nheading" }},
		{"unsafe summary", "event_public_text_invalid", func(m *DemoManifest) { m.Events[1].Summary = "unsafe\rsummary" }},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			manifest := cloneWebTestManifest(t, base)
			test.edit(&manifest)
			digest, err := DemoManifestDigest(manifest)
			if err != nil {
				t.Fatal(err)
			}
			manifest.BundleDigest = digest
			err = ValidateDemoManifestForPublication(manifest)
			webAssertPublicationCode(t, err, test.code)
		})
	}
}

type webTestArtifactReader struct {
	bodies map[string][]byte
}

func (reader *webTestArtifactReader) ReadPublicationArtifact(_ context.Context, _ string, artifactID string) ([]byte, error) {
	body, ok := reader.bodies[artifactID]
	if !ok {
		return nil, fmt.Errorf("not found")
	}
	return append([]byte(nil), body...), nil
}

type webTestPublicationStore struct {
	byID map[string]WebStoredDemo
}

func (store *webTestPublicationStore) CreateOrGetPublishedDemo(_ context.Context, candidate WebStoredDemo) (WebStoredDemo, bool, error) {
	if existing, ok := store.byID[candidate.DemoID]; ok {
		return existing, false, nil
	}
	copy := candidate
	copy.ManifestJSON = append([]byte(nil), candidate.ManifestJSON...)
	store.byID[candidate.DemoID] = copy
	return copy, true, nil
}

func webTestPublisher(manifest DemoManifest) (WebDemoPublisher, WebPublishDemoInput, *webTestArtifactReader) {
	bodies := make(map[string][]byte, len(manifest.Evidence))
	for _, reference := range manifest.Evidence {
		bodies[reference.ArtifactID] = webTestArtifactBody(reference.ArtifactID)
	}
	reader := &webTestArtifactReader{bodies: bodies}
	publisher := WebDemoPublisher{
		Artifacts: reader,
		Store:     &webTestPublicationStore{byID: make(map[string]WebStoredDemo)},
	}
	input := WebPublishDemoInput{
		Manifest: manifest,
		Trusted: WebTrustedRunPublicationRecord{
			SourceRunID: manifest.SourceRunID, DataClass: DataClassSyntheticDemo,
			State: "completed", FullyReconciled: true, OwnerApprovalVerified: true,
			PortfolioPlanDigest: manifest.PortfolioPlanDigest,
		},
	}
	return publisher, input, reader
}

func TestDemoPublisherRequiresTrustedClassificationOwnerApprovalAndArtifactBodies(t *testing.T) {
	base := webTestManifest(t)
	tests := []struct {
		name string
		code string
		edit func(*WebPublishDemoInput, *webTestArtifactReader)
	}{
		{"forged classification", "trusted_classification_not_synthetic", func(input *WebPublishDemoInput, _ *webTestArtifactReader) { input.Trusted.DataClass = DataClassPrivate }},
		{"owner approval missing", "trusted_owner_approval_missing", func(input *WebPublishDemoInput, _ *webTestArtifactReader) {
			input.Trusted.OwnerApprovalVerified = false
		}},
		{"artifact body missing", "evidence_body_missing", func(input *WebPublishDemoInput, reader *webTestArtifactReader) {
			delete(reader.bodies, input.Manifest.Evidence[0].ArtifactID)
		}},
		{"artifact body mismatch", "evidence_body_digest_mismatch", func(input *WebPublishDemoInput, reader *webTestArtifactReader) {
			reader.bodies[input.Manifest.Evidence[0].ArtifactID] = []byte("tampered")
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			publisher, input, reader := webTestPublisher(cloneWebTestManifest(t, base))
			test.edit(&input, reader)
			_, err := publisher.Publish(context.Background(), input)
			webAssertPublicationCode(t, err, test.code)
		})
	}
}

func TestDemoPublisherIsIdempotentAndCreateOnly(t *testing.T) {
	manifest := webTestManifest(t)
	publisher, input, _ := webTestPublisher(manifest)
	first, err := publisher.Publish(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if !first.Created || first.Location != "/api/web/v1/demos/"+manifest.DemoID {
		t.Fatalf("first result = %+v", first)
	}
	second, err := publisher.Publish(context.Background(), input)
	if err != nil {
		t.Fatal(err)
	}
	if second.Created || second.BundleDigest != first.BundleDigest {
		t.Fatalf("idempotent retry result = %+v", second)
	}

	different := cloneWebTestManifest(t, manifest)
	different.Title = "A different immutable publication"
	digest, err := DemoManifestDigest(different)
	if err != nil {
		t.Fatal(err)
	}
	different.BundleDigest = digest
	input.Manifest = different
	_, err = publisher.Publish(context.Background(), input)
	webAssertPublicationCode(t, err, "demo_id_already_published")
}

func TestDemoPublisherCapsPublicationAtEightMiB(t *testing.T) {
	manifest := webTestManifest(t)
	manifest.Sources[0].Source.Samples[0].RawBytesHex = strings.Repeat("aa", WebMaxPublicationBytes/2)
	digest, err := DemoManifestDigest(manifest)
	if err != nil {
		t.Fatal(err)
	}
	manifest.BundleDigest = digest
	publisher, input, _ := webTestPublisher(manifest)
	_, err = publisher.Publish(context.Background(), input)
	webAssertPublicationCode(t, err, "publication_too_large")
}

func TestGeneratedGoManifestJSONMatchesContractNames(t *testing.T) {
	manifest := webTestManifest(t)
	encoded, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(encoded, &document); err != nil {
		t.Fatal(err)
	}
	want := []string{
		"bundleDigest", "dataClass", "demoId", "events", "evidence", "experienceMode",
		"portfolioPlanDigest", "practiceApproval", "publishedAt", "reconciliation",
		"runState", "schemaVersion", "sourceRunId", "sources", "title",
	}
	got := make([]string, 0, len(document))
	for key := range document {
		got = append(got, key)
	}
	sortStrings(got)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("manifest keys = %v, want %v", got, want)
	}
}

func sortStrings(values []string) {
	for i := range values {
		for j := i + 1; j < len(values); j++ {
			if values[j] < values[i] {
				values[i], values[j] = values[j], values[i]
			}
		}
	}
}
