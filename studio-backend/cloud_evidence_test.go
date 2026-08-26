package main

import (
	"math"
	"strings"
	"testing"
)

// Helper to create a valid base set of cloud facts for testing.
func makeValidFacts() VerifiedCloudFacts {
	return VerifiedCloudFacts{
		DataflowJob: DataflowJobFact{
			Project:             "my-gcp-project",
			Region:              "us-central1",
			JobID:               "2026-08-26_18-12-59_job12345",
			TerminalState:       "JOB_STATE_DONE",
			SourceID:            "jde",
			InputArtifactDigest: "sha256:8f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			PlanDigest:          "sha256:7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
		},
		BigQueryTable: BigQueryTableWriteFact{
			Project:           "my-gcp-project",
			Dataset:           "my_dataset",
			Table:             "jde_f0101",
			SourceID:          "jde",
			CommittedRowCount: 1000,
			RejectedRowCount:  5,
			OutputDigest:      "sha256:9f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
		},
		Reconciliation: ReconciliationFact{
			SourceID:        "jde",
			RecordsRead:     1005,
			RecordsWritten:  1000,
			RecordsRejected: 5,
			InputDigest:     "sha256:8f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			PlanDigest:      "sha256:7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			OutputDigest:    "sha256:9f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
		},
	}
}

func TestVerifyAndConvert_Valid(t *testing.T) {
	sources := []string{"jde", "maxdb", "btrieve"}
	terminalStates := []string{"JOB_STATE_DONE"}
	registeredTables := map[string]string{
		"jde": "jde_f0101", "maxdb": "sap_kna1", "btrieve": "accpac_arcus",
	}

	for _, src := range sources {
		for _, state := range terminalStates {
			t.Run("source_"+src+"_state_"+state, func(t *testing.T) {
				facts := makeValidFacts()
				facts.DataflowJob.SourceID = src
				facts.DataflowJob.TerminalState = state
				facts.BigQueryTable.SourceID = src
				facts.BigQueryTable.Table = registeredTables[src]
				facts.Reconciliation.SourceID = src

				ev, err := VerifyAndConvert(&facts)
				if err != nil {
					t.Fatalf("expected no error, got %v", err)
				}
				if len(ev) != 3 {
					t.Errorf("expected 3 evidence items, got %d", len(ev))
				}
				for _, e := range ev {
					if !cpArtifactIDRe.MatchString(e.ArtifactID) {
						t.Errorf("artifact ID %q does not match regex", e.ArtifactID)
					}
					if !cpDigestRe.MatchString(e.Digest) {
						t.Errorf("digest %q does not match regex", e.Digest)
					}
				}
			})
		}
	}
}

func TestVerifyAndConvert_Adversarial(t *testing.T) {
	cases := []struct {
		name    string
		mutate  func(*VerifiedCloudFacts)
		wantErr string
	}{
		{
			name: "nil facts",
			mutate: func(f *VerifiedCloudFacts) {
				// handled by passing nil directly in test runner
			},
			wantErr: "verified cloud facts must not be nil",
		},
		{
			name: "invalid source ID",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.SourceID = "oracle"
				f.BigQueryTable.SourceID = "oracle"
				f.Reconciliation.SourceID = "oracle"
			},
			wantErr: "invalid or non-canonical source ID",
		},
		{
			name: "source ID mismatch BigQuery",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.SourceID = "maxdb"
			},
			wantErr: "source ID mismatch",
		},
		{
			name: "source ID mismatch Reconciliation",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.SourceID = "btrieve"
			},
			wantErr: "source ID mismatch",
		},
		{
			name: "unsuccessful terminal state",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.TerminalState = "JOB_STATE_RUNNING"
			},
			wantErr: "not in a successful terminal state",
		},
		{
			name: "noncanonical success alias",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.TerminalState = "success"
			},
			wantErr: "not in a successful terminal state",
		},
		{
			name: "empty terminal state",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.TerminalState = ""
			},
			wantErr: "not in a successful terminal state",
		},
		{
			name: "malformed project ID - too short",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Project = "abc"
			},
			wantErr: "malformed Dataflow project ID",
		},
		{
			name: "malformed project ID - starts with number",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Project = "1-project"
			},
			wantErr: "malformed Dataflow project ID",
		},
		{
			name: "malformed project ID - trailing hyphen",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Project = "my-project-"
			},
			wantErr: "malformed Dataflow project ID",
		},
		{
			name: "malformed project ID - uppercase",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Project = "MY-GCP-PROJECT"
			},
			wantErr: "malformed Dataflow project ID",
		},
		{
			name: "malformed region - invalid chars",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Region = "us_central1"
			},
			wantErr: "malformed Dataflow region",
		},
		{
			name: "malformed region - empty",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.Region = ""
			},
			wantErr: "malformed Dataflow region",
		},
		{
			name: "malformed job ID - empty",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.JobID = ""
			},
			wantErr: "malformed Dataflow job ID",
		},
		{
			name: "malformed job ID - too long",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.JobID = strings.Repeat("a", 129)
			},
			wantErr: "malformed Dataflow job ID",
		},
		{
			name: "malformed BigQuery project ID",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Project = "invalid_project"
			},
			wantErr: "malformed BigQuery project ID",
		},
		{
			name: "Google Cloud project mismatch",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Project = "other-gcp-project"
			},
			wantErr: "Google Cloud project binding mismatch",
		},
		{
			name: "unregistered target table",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Table = "other_table"
			},
			wantErr: "BigQuery target is not registered for source",
		},
		{
			name: "malformed dataset ID - hyphen",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Dataset = "my-dataset"
			},
			wantErr: "malformed BigQuery dataset ID",
		},
		{
			name: "malformed dataset ID - too long",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Dataset = strings.Repeat("a", 1025)
			},
			wantErr: "malformed BigQuery dataset ID",
		},
		{
			name: "malformed table ID - too long",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.Table = strings.Repeat("a", 1025)
			},
			wantErr: "malformed BigQuery table ID",
		},
		{
			name: "malformed digest - uppercase hex",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.PlanDigest = "sha256:7F43501A91E127EF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF"
			},
			wantErr: "malformed Dataflow plan digest",
		},
		{
			name: "malformed digest - missing prefix",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.PlanDigest = "7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef"
			},
			wantErr: "malformed Dataflow plan digest",
		},
		{
			name: "malformed digest - wrong length",
			mutate: func(f *VerifiedCloudFacts) {
				f.DataflowJob.PlanDigest = "sha256:7f43501a"
			},
			wantErr: "malformed Dataflow plan digest",
		},
		{
			name: "negative count - BigQuery committed",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.CommittedRowCount = -1
				f.Reconciliation.RecordsWritten = -1
			},
			wantErr: "negative BigQuery committed row count",
		},
		{
			name: "negative count - BigQuery rejected",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.RejectedRowCount = -1
				f.Reconciliation.RecordsRejected = -1
			},
			wantErr: "negative BigQuery rejected row count",
		},
		{
			name: "negative count - Reconciliation read",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.RecordsRead = -1
			},
			wantErr: "negative Reconciliation records read",
		},
		{
			name: "count overflow",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.RecordsWritten = math.MaxInt64
				f.Reconciliation.RecordsRejected = 10
				f.BigQueryTable.CommittedRowCount = math.MaxInt64
				f.BigQueryTable.RejectedRowCount = 10
			},
			wantErr: "integer overflow in reconciliation records count addition",
		},
		{
			name: "invariant read = written + rejected violated",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.RecordsRead = 1000
				f.Reconciliation.RecordsWritten = 900
				f.Reconciliation.RecordsRejected = 50
				f.BigQueryTable.CommittedRowCount = 900
				f.BigQueryTable.RejectedRowCount = 50
			},
			wantErr: "read = written + rejected invariant violated",
		},
		{
			name: "mismatched digest - input digest",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.InputDigest = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
			},
			wantErr: "digest binding mismatch",
		},
		{
			name: "mismatched digest - plan digest",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.PlanDigest = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
			},
			wantErr: "digest binding mismatch",
		},
		{
			name: "mismatched digest - output digest",
			mutate: func(f *VerifiedCloudFacts) {
				f.Reconciliation.OutputDigest = "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
			},
			wantErr: "digest binding mismatch",
		},
		{
			name: "mismatched counts - committed vs written",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.CommittedRowCount = 999
			},
			wantErr: "count binding mismatch",
		},
		{
			name: "mismatched counts - rejected vs rejected",
			mutate: func(f *VerifiedCloudFacts) {
				f.BigQueryTable.RejectedRowCount = 4
			},
			wantErr: "count binding mismatch",
		},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if c.name == "nil facts" {
				_, err := VerifyAndConvert(nil)
				if err == nil || !strings.Contains(err.Error(), c.wantErr) {
					t.Fatalf("expected error containing %q, got %v", c.wantErr, err)
				}
				return
			}

			facts := makeValidFacts()
			c.mutate(&facts)
			_, err := VerifyAndConvert(&facts)
			if err == nil {
				t.Fatalf("expected error, got none")
			}
			if !strings.Contains(err.Error(), c.wantErr) {
				t.Errorf("expected error containing %q, got %q", c.wantErr, err.Error())
			}
		})
	}
}

func TestSafeCloudSummariesNeverReflectCallerText(t *testing.T) {
	if got := SafeDataflowJobSummary("jde"); got != "Google Cloud Dataflow execution verified for JDE." {
		t.Fatalf("unexpected canonical summary: %q", got)
	}
	malicious := "attacker-controlled-project-and-table"
	for _, got := range []string{
		SafeDataflowJobSummary(malicious),
		SafeBigQueryTableSummary(malicious),
		SafeReconciliationSummary(malicious),
	} {
		if strings.Contains(got, malicious) {
			t.Fatalf("summary reflected caller text: %q", got)
		}
	}
}

func TestVerifyAndConvert_Deterministic(t *testing.T) {
	facts1 := makeValidFacts()
	facts2 := makeValidFacts()

	ev1, err := VerifyAndConvert(&facts1)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	ev2, err := VerifyAndConvert(&facts2)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(ev1) != len(ev2) {
		t.Fatalf("length mismatch: %d vs %d", len(ev1), len(ev2))
	}

	for i := range ev1 {
		if ev1[i].ArtifactID != ev2[i].ArtifactID {
			t.Errorf("artifact ID mismatch at index %d: %q vs %q", i, ev1[i].ArtifactID, ev2[i].ArtifactID)
		}
		if ev1[i].Kind != ev2[i].Kind {
			t.Errorf("kind mismatch at index %d: %q vs %q", i, ev1[i].Kind, ev2[i].Kind)
		}
		if ev1[i].Digest != ev2[i].Digest {
			t.Errorf("digest mismatch at index %d: %q vs %q", i, ev1[i].Digest, ev2[i].Digest)
		}
	}
}

func TestDecodeVerifiedCloudFacts_StrictJSON(t *testing.T) {
	validJSON := `{
		"dataflowJob": {
			"project": "my-gcp-project",
			"region": "us-central1",
			"jobId": "job123",
			"terminalState": "Done",
			"sourceId": "jde",
			"inputArtifactDigest": "sha256:8f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			"planDigest": "sha256:7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef"
		},
		"bigqueryTable": {
			"project": "my-gcp-project",
			"dataset": "my_dataset",
			"table": "my_table",
			"sourceId": "jde",
			"committedRowCount": 100,
			"rejectedRowCount": 0,
			"outputDigest": "sha256:9f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef"
		},
		"reconciliation": {
			"sourceId": "jde",
			"recordsRead": 100,
			"recordsWritten": 100,
			"recordsRejected": 0,
			"inputDigest": "sha256:8f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			"planDigest": "sha256:7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			"outputDigest": "sha256:9f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef"
		}
	}`

	facts, err := DecodeVerifiedCloudFacts([]byte(validJSON))
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if facts.DataflowJob.Project != "my-gcp-project" {
		t.Errorf("expected project 'my-gcp-project', got %q", facts.DataflowJob.Project)
	}

	// Unknown field in top level
	invalidJSONUnknown := `{
		"dataflowJob": {},
		"bigqueryTable": {},
		"reconciliation": {},
		"extraField": "value"
	}`
	_, err = DecodeVerifiedCloudFacts([]byte(invalidJSONUnknown))
	if err == nil {
		t.Fatal("expected error for unknown field, got none")
	}

	// Unknown field inside DataflowJob
	invalidJSONInnerUnknown := `{
		"dataflowJob": {
			"project": "my-gcp-project",
			"region": "us-central1",
			"jobId": "job123",
			"terminalState": "Done",
			"sourceId": "jde",
			"inputArtifactDigest": "sha256:8f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			"planDigest": "sha256:7f43501a91e127ef1234567890abcdef1234567890abcdef1234567890abcdef",
			"badField": 123
		},
		"bigqueryTable": {},
		"reconciliation": {}
	}`
	_, err = DecodeVerifiedCloudFacts([]byte(invalidJSONInnerUnknown))
	if err == nil {
		t.Fatal("expected error for unknown inner field, got none")
	}

	// Trailing data
	invalidJSONTrailing := validJSON + "\n{}"
	_, err = DecodeVerifiedCloudFacts([]byte(invalidJSONTrailing))
	if err == nil {
		t.Fatal("expected error for trailing data, got none")
	}
}
