package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"strings"
)

// DataflowJobFact represents the verified execution facts of a Dataflow job on Google Cloud.
type DataflowJobFact struct {
	Project             string `json:"project"`
	Region              string `json:"region"`
	JobID               string `json:"jobId"`
	TerminalState       string `json:"terminalState"`
	SourceID            string `json:"sourceId"`
	InputArtifactDigest string `json:"inputArtifactDigest"`
	PlanDigest          string `json:"planDigest"`
}

// BigQueryTableWriteFact represents the verified execution facts of a BigQuery table write.
type BigQueryTableWriteFact struct {
	Project           string `json:"project"`
	Dataset           string `json:"dataset"`
	Table             string `json:"table"`
	SourceID          string `json:"sourceId"`
	CommittedRowCount int64  `json:"committedRowCount"`
	RejectedRowCount  int64  `json:"rejectedRowCount"`
	OutputDigest      string `json:"outputDigest"`
}

// ReconciliationFact represents the verified data reconciliation facts.
type ReconciliationFact struct {
	SourceID        string `json:"sourceId"`
	RecordsRead     int64  `json:"recordsRead"`
	RecordsWritten  int64  `json:"recordsWritten"`
	RecordsRejected int64  `json:"recordsRejected"`
	InputDigest     string `json:"inputDigest"`
	PlanDigest      string `json:"planDigest"`
	OutputDigest    string `json:"outputDigest"`
}

// VerifiedCloudFacts groups the three fact types representing Google Cloud execution facts.
type VerifiedCloudFacts struct {
	DataflowJob    DataflowJobFact        `json:"dataflowJob"`
	BigQueryTable  BigQueryTableWriteFact `json:"bigqueryTable"`
	Reconciliation ReconciliationFact     `json:"reconciliation"`
}

// Compiled regexes for GCP identifier and digest validation.
var (
	projectIDRe = regexp.MustCompile("^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
	regionRe    = regexp.MustCompile("^[a-z][a-z0-9-]{1,61}[a-z0-9]$")
	jobIDRe     = regexp.MustCompile("^[a-zA-Z0-9_-]{1,128}$")
	datasetIDRe = regexp.MustCompile("^[a-zA-Z0-9_]+$")
	tableIDRe   = regexp.MustCompile("^[a-zA-Z0-9_-]+$")
	digestRe    = regexp.MustCompile("^sha256:[a-f0-9]{64}$")
)

// DecodeVerifiedCloudFacts decodes VerifiedCloudFacts from JSON, rejecting unknown fields.
func DecodeVerifiedCloudFacts(data []byte) (*VerifiedCloudFacts, error) {
	dec := json.NewDecoder(strings.NewReader(string(data)))
	dec.DisallowUnknownFields()
	var facts VerifiedCloudFacts
	if err := dec.Decode(&facts); err != nil {
		return nil, fmt.Errorf("failed to decode facts: %w", err)
	}
	var dummy struct{}
	if err := dec.Decode(&dummy); err != io.EOF {
		return nil, errors.New("trailing data after JSON facts")
	}
	return &facts, nil
}

// VerifyAndConvert checks the validity and structural integrity of the execution facts,
// and produces a slice of three ControlPlaneEvidence objects with deterministic artifact IDs and digests.
// It fails closed and returns an error if any invariant is violated.
func VerifyAndConvert(facts *VerifiedCloudFacts) ([]ControlPlaneEvidence, error) {
	if facts == nil {
		return nil, errors.New("verified cloud facts must not be nil")
	}

	// 1. Accept only canonical source IDs: jde, maxdb, btrieve
	sourceID := facts.DataflowJob.SourceID
	if sourceID != "jde" && sourceID != "maxdb" && sourceID != "btrieve" {
		return nil, errors.New("invalid or non-canonical source ID")
	}
	if facts.BigQueryTable.SourceID != sourceID {
		return nil, errors.New("source ID mismatch")
	}
	if facts.Reconciliation.SourceID != sourceID {
		return nil, errors.New("source ID mismatch")
	}

	// 2. Require the Dataflow job to be in a successful terminal state
	if facts.DataflowJob.TerminalState != "JOB_STATE_DONE" {
		return nil, errors.New("dataflow job is not in a successful terminal state")
	}

	// 3. Validate bounded Google identifiers
	if !projectIDRe.MatchString(facts.DataflowJob.Project) {
		return nil, errors.New("malformed Dataflow project ID")
	}
	if !regionRe.MatchString(facts.DataflowJob.Region) {
		return nil, errors.New("malformed Dataflow region")
	}
	if !jobIDRe.MatchString(facts.DataflowJob.JobID) {
		return nil, errors.New("malformed Dataflow job ID")
	}
	if !projectIDRe.MatchString(facts.BigQueryTable.Project) {
		return nil, errors.New("malformed BigQuery project ID")
	}
	if len(facts.BigQueryTable.Dataset) > 1024 || !datasetIDRe.MatchString(facts.BigQueryTable.Dataset) {
		return nil, errors.New("malformed BigQuery dataset ID")
	}
	if len(facts.BigQueryTable.Table) > 1024 || !tableIDRe.MatchString(facts.BigQueryTable.Table) {
		return nil, errors.New("malformed BigQuery table ID")
	}
	if facts.DataflowJob.Project != facts.BigQueryTable.Project {
		return nil, errors.New("Google Cloud project binding mismatch")
	}
	registeredTable := map[string]string{
		"jde":     "jde_f0101",
		"maxdb":   "sap_kna1",
		"btrieve": "accpac_arcus",
	}[sourceID]
	if facts.BigQueryTable.Table != registeredTable {
		return nil, errors.New("BigQuery target is not registered for source")
	}

	// 4. Validate canonical lowercase sha256: digests
	if !digestRe.MatchString(facts.DataflowJob.InputArtifactDigest) {
		return nil, errors.New("malformed Dataflow input artifact digest")
	}
	if !digestRe.MatchString(facts.DataflowJob.PlanDigest) {
		return nil, errors.New("malformed Dataflow plan digest")
	}
	if !digestRe.MatchString(facts.BigQueryTable.OutputDigest) {
		return nil, errors.New("malformed BigQuery output digest")
	}
	if !digestRe.MatchString(facts.Reconciliation.InputDigest) {
		return nil, errors.New("malformed Reconciliation input digest")
	}
	if !digestRe.MatchString(facts.Reconciliation.PlanDigest) {
		return nil, errors.New("malformed Reconciliation plan digest")
	}
	if !digestRe.MatchString(facts.Reconciliation.OutputDigest) {
		return nil, errors.New("malformed Reconciliation output digest")
	}

	// 5. Validate nonnegative counts
	if facts.BigQueryTable.CommittedRowCount < 0 {
		return nil, errors.New("negative BigQuery committed row count")
	}
	if facts.BigQueryTable.RejectedRowCount < 0 {
		return nil, errors.New("negative BigQuery rejected row count")
	}
	if facts.Reconciliation.RecordsRead < 0 {
		return nil, errors.New("negative Reconciliation records read")
	}
	if facts.Reconciliation.RecordsWritten < 0 {
		return nil, errors.New("negative Reconciliation records written")
	}
	if facts.Reconciliation.RecordsRejected < 0 {
		return nil, errors.New("negative Reconciliation records rejected")
	}

	// Check for addition overflow
	if facts.Reconciliation.RecordsWritten > math.MaxInt64-facts.Reconciliation.RecordsRejected {
		return nil, errors.New("integer overflow in reconciliation records count addition")
	}

	// 6. Validate invariant read = written + rejected
	sumWrittenRejected := facts.Reconciliation.RecordsWritten + facts.Reconciliation.RecordsRejected
	if facts.Reconciliation.RecordsRead != sumWrittenRejected {
		return nil, errors.New("read = written + rejected invariant violated")
	}

	// 7. Ensure all facts bind the same plan/output chain
	if facts.DataflowJob.InputArtifactDigest != facts.Reconciliation.InputDigest {
		return nil, errors.New("digest binding mismatch")
	}
	if facts.DataflowJob.PlanDigest != facts.Reconciliation.PlanDigest {
		return nil, errors.New("digest binding mismatch")
	}
	if facts.BigQueryTable.OutputDigest != facts.Reconciliation.OutputDigest {
		return nil, errors.New("digest binding mismatch")
	}
	if facts.BigQueryTable.CommittedRowCount != facts.Reconciliation.RecordsWritten {
		return nil, errors.New("count binding mismatch")
	}
	if facts.BigQueryTable.RejectedRowCount != facts.Reconciliation.RecordsRejected {
		return nil, errors.New("count binding mismatch")
	}

	// 8. Produce only existing frozen evidence kinds with deterministic artifact IDs and deterministic digests
	// Compute deterministic digests by JSON-marshaling the validated sub-facts.
	dfDigest, err := computeJSONDigest(facts.DataflowJob)
	if err != nil {
		return nil, fmt.Errorf("failed to compute Dataflow job digest: %w", err)
	}
	bqDigest, err := computeJSONDigest(facts.BigQueryTable)
	if err != nil {
		return nil, fmt.Errorf("failed to compute BigQuery table digest: %w", err)
	}
	recDigest, err := computeJSONDigest(facts.Reconciliation)
	if err != nil {
		return nil, fmt.Errorf("failed to compute Reconciliation digest: %w", err)
	}

	// Compute deterministic artifact IDs using hashes of the identifiers.
	// This ensures that project IDs, dataset names, etc., do not leak in the artifact IDs,
	// while keeping them unique and conforming to the control plane regex pattern.
	dfHashInput := fmt.Sprintf("%s:%s:%s", facts.DataflowJob.Project, facts.DataflowJob.Region, facts.DataflowJob.JobID)
	dfHash := sha256.Sum256([]byte(dfHashInput))
	dfArtifactID := fmt.Sprintf("art_dataflow_%s_%s", sourceID, hex.EncodeToString(dfHash[:]))

	bqHashInput := fmt.Sprintf("%s:%s:%s", facts.BigQueryTable.Project, facts.BigQueryTable.Dataset, facts.BigQueryTable.Table)
	bqHash := sha256.Sum256([]byte(bqHashInput))
	bqArtifactID := fmt.Sprintf("art_bigquery_%s_%s", sourceID, hex.EncodeToString(bqHash[:]))

	recHashInput := fmt.Sprintf("%s:%s:%s:%s", sourceID, facts.Reconciliation.InputDigest, facts.Reconciliation.PlanDigest, facts.Reconciliation.OutputDigest)
	recHash := sha256.Sum256([]byte(recHashInput))
	recArtifactID := fmt.Sprintf("art_reconciliation_%s_%s", sourceID, hex.EncodeToString(recHash[:]))

	evidence := []ControlPlaneEvidence{
		{
			ArtifactID: dfArtifactID,
			Kind:       "dataflow_job",
			Digest:     dfDigest,
		},
		{
			ArtifactID: bqArtifactID,
			Kind:       "bigquery_table",
			Digest:     bqDigest,
		},
		{
			ArtifactID: recArtifactID,
			Kind:       "reconciliation",
			Digest:     recDigest,
		},
	}

	return evidence, nil
}

// SafeDataflowJobSummary returns a generic API summary for Dataflow job verification,
// avoiding any project ID, region, or job ID leakage.
func SafeDataflowJobSummary(sourceID string) string {
	return safeCloudSummary("Google Cloud Dataflow execution verified", sourceID)
}

// SafeBigQueryTableSummary returns a generic API summary for BigQuery table write verification,
// avoiding any project ID, dataset, or table name leakage.
func SafeBigQueryTableSummary(sourceID string) string {
	return safeCloudSummary("BigQuery target table write verified", sourceID)
}

// SafeReconciliationSummary returns a generic API summary for reconciliation verification,
// avoiding any row count or digest leakage.
func SafeReconciliationSummary(sourceID string) string {
	return safeCloudSummary("End-to-end data reconciliation verified", sourceID)
}

func safeCloudSummary(prefix, sourceID string) string {
	label := cpSourceLabel(sourceID)
	if label == "" {
		return prefix + "."
	}
	return prefix + " for " + label + "."
}

func computeJSONDigest(val any) (string, error) {
	data, err := json.Marshal(val)
	if err != nil {
		return "", err
	}
	hash := sha256.Sum256(data)
	return "sha256:" + hex.EncodeToString(hash[:]), nil
}
