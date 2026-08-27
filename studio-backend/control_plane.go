package main

// control_plane.go implements the frozen zero-trust migration control-plane
// API (contracts/openapi.json, contract version 1.0.0) on top of a durable,
// single-file JSON snapshot.
//
// Design rules enforced here:
//
//   - Every mutation holds one mutex, is applied to a copy-on-write snapshot,
//     is re-validated, and is then written atomically (0600 temp file, fsync,
//     rename, parent directory fsync) before it becomes visible in memory.
//   - Loading refuses unknown fields, unknown versions, duplicate identifiers
//     and any run/event/approval link that does not reconcile.
//   - Every request is authenticated with an exact constant-time comparison of
//     the whole Authorization header.
//   - Errors are closed application/problem+json documents built only from
//     compile-time constants; request bodies, tokens, paths and internal error
//     text are never echoed.
//   - Event summaries are generated from a fixed vocabulary. Caller-supplied
//     free text never reaches an event, a summary, or a response.

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

// ---------------------------------------------------------------------------
// Contract constants
// ---------------------------------------------------------------------------

const (
	// cpSchemaVersion is the frozen contract version. It is the only value
	// accepted on the wire and the only value accepted from disk.
	cpSchemaVersion = "1.0.0"

	// cpSnapshotVersion versions the on-disk snapshot envelope. It is
	// deliberately independent of the wire contract version.
	cpSnapshotVersion = 1

	// cpMaxRequestBody bounds every request body read by this handler.
	cpMaxRequestBody = 64 << 10

	// cpMaxSSEReplay bounds how many stored events one SSE response replays.
	// A truncated stream ends cleanly; the client resumes with Last-Event-ID.
	cpMaxSSEReplay = 500

	// cpSSERetryMillis is the reconnection hint sent at the head of a stream.
	cpSSERetryMillis = 2000

	// cpMaxEventsPerRun bounds the event log of a single portfolio.
	cpMaxEventsPerRun = 10000

	// cpMaxRuns bounds the total number of stored portfolios.
	cpMaxRuns = 1000

	cpMaxSummaryRunes   = 280
	cpMaxNameRunes      = 120
	cpMaxReasonRunes    = 500
	cpMaxEvidencePerEvt = 50

	// cpTimeFormat is an RFC 3339 date-time with fixed millisecond precision,
	// so persisted timestamps sort lexicographically as well as temporally.
	cpTimeFormat = "2006-01-02T15:04:05.000Z"

	cpProblemTypeBase = "https://zero-trust-migration.example/problems/"

	// cpIDEntropyChars is the number of random alphanumeric characters in a
	// generated identifier; with the 4-character prefix this satisfies the
	// frozen {12,64} identifier patterns.
	cpIDEntropyChars = 16
)

// ControlPlaneState is one member of the frozen runState vocabulary.
type ControlPlaneState string

// The frozen runState vocabulary.
const (
	ControlPlaneStateCreated          ControlPlaneState = "created"
	ControlPlaneStateInventorying     ControlPlaneState = "inventorying"
	ControlPlaneStateRedacting        ControlPlaneState = "redacting"
	ControlPlaneStatePlanning         ControlPlaneState = "planning"
	ControlPlaneStateAwaitingApproval ControlPlaneState = "awaiting_approval"
	ControlPlaneStateApproved         ControlPlaneState = "approved"
	ControlPlaneStateExecuting        ControlPlaneState = "executing"
	ControlPlaneStateVerifying        ControlPlaneState = "verifying"
	ControlPlaneStateCompleted        ControlPlaneState = "completed"
	ControlPlaneStateFailed           ControlPlaneState = "failed"
	ControlPlaneStateCancelled        ControlPlaneState = "cancelled"
)

// cpProgressRank orders the non-terminal portion of the frozen sequence. The
// portfolio state is the least advanced source state, so a portfolio can never
// report progress that one of its sources has not actually made.
var cpProgressRank = map[ControlPlaneState]int{
	ControlPlaneStateCreated:          0,
	ControlPlaneStateInventorying:     1,
	ControlPlaneStateRedacting:        2,
	ControlPlaneStatePlanning:         3,
	ControlPlaneStateAwaitingApproval: 4,
	ControlPlaneStateApproved:         5,
	ControlPlaneStateExecuting:        6,
	ControlPlaneStateVerifying:        7,
	ControlPlaneStateCompleted:        8,
}

func cpIsKnownState(s ControlPlaneState) bool {
	if _, ok := cpProgressRank[s]; ok {
		return true
	}
	return s == ControlPlaneStateFailed || s == ControlPlaneStateCancelled
}

func cpIsTerminalState(s ControlPlaneState) bool {
	return s == ControlPlaneStateCompleted ||
		s == ControlPlaneStateFailed ||
		s == ControlPlaneStateCancelled
}

// cpCanonicalSources is the only accepted source set: exactly these three
// sourceId/hostname pairs, each exactly once. Storage always uses this order.
var cpCanonicalSources = []struct {
	SourceID string
	Hostname string
	Label    string
}{
	{SourceID: "jde", Hostname: "legacy-jde-db", Label: "JDE"},
	{SourceID: "maxdb", Hostname: "legacy-maxdb", Label: "MaxDB"},
	{SourceID: "btrieve", Hostname: "legacy-btrieve-db", Label: "Btrieve"},
}

func cpCanonicalHostname(sourceID string) (string, bool) {
	for _, c := range cpCanonicalSources {
		if c.SourceID == sourceID {
			return c.Hostname, true
		}
	}
	return "", false
}

func cpSourceLabel(sourceID string) string {
	for _, c := range cpCanonicalSources {
		if c.SourceID == sourceID {
			return c.Label
		}
	}
	return ""
}

// cpEventSourceScoped maps the frozen SSE eventType vocabulary to its scope:
// true for source-scoped events (which must carry sourceId) and false for
// portfolio-scoped events (which must not).
var cpEventSourceScoped = map[string]bool{
	"source.inventory.started":      true,
	"source.inventory.completed":    true,
	"source.redaction.completed":    true,
	"source.plan.ready":             true,
	"source.execution.started":      true,
	"source.execution.completed":    true,
	"source.verification.completed": true,
	"source.failed":                 true,
	"migration.created":             false,
	"portfolio.awaiting_approval":   false,
	"portfolio.approved":            false,
	"portfolio.rejected":            false,
	"migration.completed":           false,
	"migration.failed":              false,
	"migration.cancelled":           false,
}

// cpEvidenceKinds is the frozen evidenceReference kind vocabulary.
var cpEvidenceKinds = map[string]bool{
	"source_manifest":  true,
	"redaction_report": true,
	"transform_plan":   true,
	"dataflow_job":     true,
	"bigquery_table":   true,
	"reconciliation":   true,
	"audit_log":        true,
}

var (
	cpRunIDRe         = regexp.MustCompile(`^mig_[A-Za-z0-9]{12,64}$`)
	cpEventIDRe       = regexp.MustCompile(`^evt_[A-Za-z0-9]{12,64}$`)
	cpApprovalIDRe    = regexp.MustCompile(`^apr_[A-Za-z0-9]{12,64}$`)
	cpArtifactIDRe    = regexp.MustCompile(`^art_[A-Za-z0-9._-]{8,128}$`)
	cpDigestRe        = regexp.MustCompile(`^sha256:[a-f0-9]{64}$`)
	cpPortfolioNameRe = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9 _.-]*$`)
	cpActorRe         = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9@._ -]*$`)
	cpFailureCodeRe   = regexp.MustCompile(`^[A-Z][A-Z0-9_]{2,63}$`)
)

// ---------------------------------------------------------------------------
// Persisted model
// ---------------------------------------------------------------------------

// ControlPlaneSource is the persisted per-source progress record. It is a
// superset of the contract sourceProgress object: recordDigest and
// planArtifactId are internal evidence bindings and are never serialised onto
// the wire, because the contract object is closed.
type ControlPlaneSource struct {
	SourceID        string            `json:"sourceId"`
	Hostname        string            `json:"hostname"`
	State           ControlPlaneState `json:"state"`
	RecordsRead     int64             `json:"recordsRead"`
	RecordsWritten  int64             `json:"recordsWritten"`
	RecordsRejected int64             `json:"recordsRejected"`
	PlanDigest      string            `json:"planDigest,omitempty"`
	FailureCode     string            `json:"failureCode,omitempty"`
	RecordDigest    string            `json:"recordDigest,omitempty"`
	PlanArtifactID  string            `json:"planArtifactId,omitempty"`
}

// ControlPlaneRun is the persisted portfolio record.
type ControlPlaneRun struct {
	RunID               string               `json:"runId"`
	PortfolioName       string               `json:"portfolioName"`
	State               ControlPlaneState    `json:"state"`
	Sources             []ControlPlaneSource `json:"sources"`
	PortfolioPlanDigest string               `json:"portfolioPlanDigest,omitempty"`
	FailureCode         string               `json:"failureCode,omitempty"`
	RequestedBy         string               `json:"requestedBy,omitempty"`
	ApprovalID          string               `json:"approvalId,omitempty"`
	CreatedAt           string               `json:"createdAt"`
	UpdatedAt           string               `json:"updatedAt"`
}

// ControlPlaneEvidence is one frozen evidenceReference.
type ControlPlaneEvidence struct {
	ArtifactID string `json:"artifactId"`
	Kind       string `json:"kind"`
	Digest     string `json:"digest"`
}

// ControlPlaneEvent is one persisted, immutable, ordered event.
type ControlPlaneEvent struct {
	Seq                uint64                 `json:"seq"`
	EventID            string                 `json:"eventId"`
	RunID              string                 `json:"runId"`
	SourceID           string                 `json:"sourceId,omitempty"`
	EventType          string                 `json:"eventType"`
	Timestamp          string                 `json:"timestamp"`
	Summary            string                 `json:"summary"`
	EvidenceReferences []ControlPlaneEvidence `json:"evidenceReferences"`
	State              ControlPlaneState      `json:"state"`
}

// ControlPlaneApproval is the single immutable decision recorded for a run.
type ControlPlaneApproval struct {
	ApprovalID     string            `json:"approvalId"`
	RunID          string            `json:"runId"`
	PlanDigest     string            `json:"planDigest"`
	Decision       string            `json:"decision"`
	ResultingState ControlPlaneState `json:"resultingState"`
	DecidedBy      string            `json:"decidedBy"`
	DecidedAt      string            `json:"decidedAt"`
	Reason         string            `json:"reason,omitempty"`
}

// cpSnapshot is the versioned on-disk envelope holding the entire state.
type cpSnapshot struct {
	SnapshotVersion int                     `json:"snapshotVersion"`
	SchemaVersion   string                  `json:"schemaVersion"`
	NextSeq         uint64                  `json:"nextSeq"`
	Runs            []*ControlPlaneRun      `json:"runs"`
	Approvals       []*ControlPlaneApproval `json:"approvals"`
	Events          []*ControlPlaneEvent    `json:"events"`
}

func (r *ControlPlaneRun) clone() *ControlPlaneRun {
	if r == nil {
		return nil
	}
	out := *r
	out.Sources = append([]ControlPlaneSource(nil), r.Sources...)
	return &out
}

func (e *ControlPlaneEvent) clone() *ControlPlaneEvent {
	if e == nil {
		return nil
	}
	out := *e
	out.EvidenceReferences = append([]ControlPlaneEvidence(nil), e.EvidenceReferences...)
	if out.EvidenceReferences == nil {
		out.EvidenceReferences = []ControlPlaneEvidence{}
	}
	return &out
}

// ---------------------------------------------------------------------------
// Closed problem vocabulary
// ---------------------------------------------------------------------------

// cpFault is an internal error carrying only constant, caller-safe text.
type cpFault struct {
	Status int
	Slug   string
	Title  string
	Detail string
}

func (f *cpFault) Error() string { return f.Slug }

var (
	cpErrUnauthorized = &cpFault{
		Status: http.StatusUnauthorized, Slug: "unauthorized",
		Title:  "Unauthorized",
		Detail: "A valid bearer credential is required.",
	}
	cpErrNotFound = &cpFault{
		Status: http.StatusNotFound, Slug: "not-found",
		Title:  "Not found",
		Detail: "No matching migration resource exists.",
	}
	cpErrMalformedBody = &cpFault{
		Status: http.StatusBadRequest, Slug: "malformed-body",
		Title:  "Malformed request body",
		Detail: "The body must be exactly one JSON document with no unknown fields.",
	}
	cpErrInvalidRequest = &cpFault{
		Status: http.StatusBadRequest, Slug: "invalid-request",
		Title:  "Invalid request",
		Detail: "The request does not satisfy the frozen migration contract.",
	}
	cpErrInvalidSources = &cpFault{
		Status: http.StatusBadRequest, Slug: "invalid-sources",
		Title:  "Invalid source set",
		Detail: "Exactly the three canonical legacy source and hostname pairs are accepted.",
	}
	cpErrInvalidDigest = &cpFault{
		Status: http.StatusBadRequest, Slug: "invalid-digest",
		Title:  "Invalid plan digest",
		Detail: "The plan digest must be a lowercase sha256 digest.",
	}
	cpErrInvalidCursor = &cpFault{
		Status: http.StatusBadRequest, Slug: "invalid-cursor",
		Title:  "Invalid event cursor",
		Detail: "Last-Event-ID must be a single well-formed event identifier.",
	}
	cpErrUnknownCursor = &cpFault{
		Status: http.StatusNotFound, Slug: "unknown-cursor",
		Title:  "Unknown event cursor",
		Detail: "Last-Event-ID does not identify an event in this stream.",
	}
	cpErrUnsupportedMedia = &cpFault{
		Status: http.StatusUnsupportedMediaType, Slug: "unsupported-media-type",
		Title:  "Unsupported media type",
		Detail: "Request bodies must be application/json.",
	}
	cpErrPayloadTooLarge = &cpFault{
		Status: http.StatusRequestEntityTooLarge, Slug: "payload-too-large",
		Title:  "Request body too large",
		Detail: "The request body exceeds the accepted size limit.",
	}
	cpErrMethodNotAllowed = &cpFault{
		Status: http.StatusMethodNotAllowed, Slug: "method-not-allowed",
		Title:  "Method not allowed",
		Detail: "This endpoint does not accept the requested method.",
	}
	cpErrPortfolioExists = &cpFault{
		Status: http.StatusConflict, Slug: "portfolio-exists",
		Title:  "Portfolio already active",
		Detail: "An active portfolio with this name already exists.",
	}
	cpErrCapacity = &cpFault{
		Status: http.StatusConflict, Slug: "capacity-exhausted",
		Title:  "Capacity exhausted",
		Detail: "The control plane cannot accept another portfolio.",
	}
	cpErrNotAwaitingApproval = &cpFault{
		Status: http.StatusConflict, Slug: "not-awaiting-approval",
		Title:  "Approval not pending",
		Detail: "The portfolio is not awaiting an approval decision.",
	}
	cpErrStaleDigest = &cpFault{
		Status: http.StatusConflict, Slug: "stale-plan-digest",
		Title:  "Stale plan digest",
		Detail: "The supplied plan digest does not match the current portfolio plan.",
	}
	cpErrAlreadyDecided = &cpFault{
		Status: http.StatusConflict, Slug: "already-decided",
		Title:  "Decision already recorded",
		Detail: "This portfolio already carries an immutable approval decision.",
	}
	cpErrInvalidTransition = &cpFault{
		Status: http.StatusConflict, Slug: "invalid-transition",
		Title:  "Invalid state transition",
		Detail: "The requested transition is not part of the frozen migration sequence.",
	}
	cpErrTerminal = &cpFault{
		Status: http.StatusConflict, Slug: "run-terminal",
		Title:  "Portfolio is terminal",
		Detail: "The portfolio reached a terminal state and can no longer be mutated.",
	}
	cpErrEventLimit = &cpFault{
		Status: http.StatusConflict, Slug: "event-limit",
		Title:  "Event limit reached",
		Detail: "The portfolio event log is full.",
	}
	cpErrInternal = &cpFault{
		Status: http.StatusInternalServerError, Slug: "internal-error",
		Title:  "Internal error",
		Detail: "The request could not be completed.",
	}
)

// cpProblemBody is the closed application/problem+json document.
type cpProblemBody struct {
	SchemaVersion string `json:"schemaVersion"`
	Type          string `json:"type"`
	Title         string `json:"title"`
	Status        int    `json:"status"`
	Detail        string `json:"detail,omitempty"`
}

// cpWriteProblem emits a problem document built only from constants.
func cpWriteProblem(w http.ResponseWriter, err error) {
	f := cpErrInternal
	var typed *cpFault
	if errors.As(err, &typed) && typed != nil {
		f = typed
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(f.Status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(true)
	_ = enc.Encode(cpProblemBody{
		SchemaVersion: cpSchemaVersion,
		Type:          cpProblemTypeBase + f.Slug,
		Title:         f.Title,
		Status:        f.Status,
		Detail:        f.Detail,
	})
}

// ---------------------------------------------------------------------------
// Text and identifier helpers
// ---------------------------------------------------------------------------

// cpIsSafeText reports whether s is storable, renderable free text: valid
// UTF-8, within the rune budget, free of control characters, and free of the
// characters used to break out of HTML or markup contexts.
func cpIsSafeText(s string, maxRunes int) bool {
	if s == "" || !utf8.ValidString(s) {
		return false
	}
	if utf8.RuneCountInString(s) > maxRunes {
		return false
	}
	for _, r := range s {
		if r < 0x20 || r == 0x7f {
			return false
		}
		switch r {
		case '<', '>', '&', '"', '\'', '`', '\\':
			return false
		}
	}
	return true
}

// cpIsBoundedName validates a contract string with a rune budget and pattern.
func cpIsBoundedName(s string, maxRunes int, re *regexp.Regexp) bool {
	if s == "" || !utf8.ValidString(s) {
		return false
	}
	if utf8.RuneCountInString(s) > maxRunes {
		return false
	}
	return re.MatchString(s)
}

const cpIDAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

// cpRandomID returns prefix followed by n unbiased random alphanumerics.
func cpRandomID(prefix string, n int) (string, error) {
	out := make([]byte, 0, n)
	buf := make([]byte, n)
	// 248 == 62*4: rejecting bytes at or above it removes modulo bias.
	const limit = 248
	for len(out) < n {
		if _, err := rand.Read(buf); err != nil {
			return "", err
		}
		for _, b := range buf {
			if int(b) >= limit {
				continue
			}
			out = append(out, cpIDAlphabet[int(b)%len(cpIDAlphabet)])
			if len(out) == n {
				break
			}
		}
	}
	return prefix + string(out), nil
}

// cpPortfolioPlanDigest implements the language-neutral canonical digest used
// by control_plane/canonical.py. Each plan digest already binds its run ID, so
// the portfolio anchor contains only the frozen schema version and the three
// source/digest pairs in canonical order.
func cpPortfolioPlanDigest(run *ControlPlaneRun) string {
	plans := make([]map[string]string, 0, len(cpCanonicalSources))
	for _, c := range cpCanonicalSources {
		src := cpFindSource(run, c.SourceID)
		if src == nil {
			return ""
		}
		plans = append(plans, map[string]string{
			"sourceId":   c.SourceID,
			"planDigest": src.PlanDigest,
		})
	}
	payload := map[string]any{
		"schemaVersion": cpSchemaVersion,
		"plans":         plans,
	}
	encoded, err := json.Marshal(payload)
	if err != nil { // The payload contains only repository-owned JSON values.
		return ""
	}
	digest := sha256.Sum256(encoded)
	return "sha256:" + hex.EncodeToString(digest[:])
}

func cpFindSource(run *ControlPlaneRun, sourceID string) *ControlPlaneSource {
	for i := range run.Sources {
		if run.Sources[i].SourceID == sourceID {
			return &run.Sources[i]
		}
	}
	return nil
}

func cpFindRun(snap *cpSnapshot, runID string) *ControlPlaneRun {
	for _, r := range snap.Runs {
		if r.RunID == runID {
			return r
		}
	}
	return nil
}

// cpDeriveRunState computes the portfolio state from its sources: a failure
// anywhere fails the portfolio, a cancellation anywhere cancels it, and
// otherwise the portfolio reports the least advanced source state.
func cpDeriveRunState(sources []ControlPlaneSource) ControlPlaneState {
	if len(sources) == 0 {
		return ""
	}
	failed, cancelled := false, false
	least := ControlPlaneState("")
	leastRank := int(^uint(0) >> 1)
	for _, s := range sources {
		switch s.State {
		case ControlPlaneStateFailed:
			failed = true
		case ControlPlaneStateCancelled:
			cancelled = true
		default:
			r, ok := cpProgressRank[s.State]
			if !ok {
				return ""
			}
			if r < leastRank {
				leastRank, least = r, s.State
			}
		}
	}
	if failed {
		return ControlPlaneStateFailed
	}
	if cancelled {
		return ControlPlaneStateCancelled
	}
	return least
}

func cpParseStamp(s string) (time.Time, bool) {
	t, err := time.Parse(time.RFC3339, s)
	if err != nil {
		return time.Time{}, false
	}
	return t.UTC(), true
}

// ---------------------------------------------------------------------------
// Snapshot integrity
// ---------------------------------------------------------------------------

// errCorruptState is returned whenever a snapshot fails integrity checks. The
// wrapped reason names the kind of inconsistency only; it never contains a
// file path, a token, or any stored value.
var errCorruptState = errors.New("control plane: state snapshot is corrupt")

func cpCorrupt(reason string) error {
	return fmt.Errorf("%w: %s", errCorruptState, reason)
}

// cpValidateSnapshot enforces every structural and referential invariant the
// control plane relies on. It runs when state is loaded from disk and again
// before any mutation is committed, so a bug in a transition can never write
// an inconsistent snapshot.
func cpValidateSnapshot(snap *cpSnapshot) error {
	if snap == nil {
		return cpCorrupt("missing snapshot")
	}
	if snap.SnapshotVersion != cpSnapshotVersion {
		return cpCorrupt("unsupported snapshot version")
	}
	if snap.SchemaVersion != cpSchemaVersion {
		return cpCorrupt("unsupported contract version")
	}
	if len(snap.Runs) > cpMaxRuns {
		return cpCorrupt("run capacity exceeded")
	}

	runs := make(map[string]*ControlPlaneRun, len(snap.Runs))
	for _, run := range snap.Runs {
		if run == nil {
			return cpCorrupt("nil run")
		}
		if !cpRunIDRe.MatchString(run.RunID) {
			return cpCorrupt("malformed run id")
		}
		if _, dup := runs[run.RunID]; dup {
			return cpCorrupt("duplicate run id")
		}
		if err := cpValidateRun(run); err != nil {
			return err
		}
		runs[run.RunID] = run
	}

	if err := cpValidateApprovals(snap, runs); err != nil {
		return err
	}
	return cpValidateEvents(snap, runs)
}

func cpValidateRun(run *ControlPlaneRun) error {
	if !cpIsBoundedName(run.PortfolioName, cpMaxNameRunes, cpPortfolioNameRe) {
		return cpCorrupt("malformed portfolio name")
	}
	if run.RequestedBy != "" && !cpIsBoundedName(run.RequestedBy, cpMaxNameRunes, cpActorRe) {
		return cpCorrupt("malformed requester")
	}
	if !cpIsKnownState(run.State) {
		return cpCorrupt("unknown run state")
	}
	if run.FailureCode != "" && !cpFailureCodeRe.MatchString(run.FailureCode) {
		return cpCorrupt("malformed run failure code")
	}
	if (run.State == ControlPlaneStateFailed) != (run.FailureCode != "") {
		return cpCorrupt("failure code does not match run state")
	}
	if len(run.Sources) != len(cpCanonicalSources) {
		return cpCorrupt("run does not carry exactly three sources")
	}
	for i, c := range cpCanonicalSources {
		src := run.Sources[i]
		if src.SourceID != c.SourceID || src.Hostname != c.Hostname {
			return cpCorrupt("non-canonical source descriptor")
		}
		if !cpIsKnownState(src.State) {
			return cpCorrupt("unknown source state")
		}
		if src.RecordsRead < 0 || src.RecordsWritten < 0 || src.RecordsRejected < 0 {
			return cpCorrupt("negative source counter")
		}
		if src.PlanDigest != "" && !cpDigestRe.MatchString(src.PlanDigest) {
			return cpCorrupt("malformed source plan digest")
		}
		if src.RecordDigest != "" && !cpDigestRe.MatchString(src.RecordDigest) {
			return cpCorrupt("malformed source record digest")
		}
		if src.PlanArtifactID != "" && !cpArtifactIDRe.MatchString(src.PlanArtifactID) {
			return cpCorrupt("malformed source plan artifact id")
		}
		if (src.PlanDigest != "") != (src.PlanArtifactID != "") {
			return cpCorrupt("source plan digest is not bound to an artifact")
		}
		if src.FailureCode != "" && !cpFailureCodeRe.MatchString(src.FailureCode) {
			return cpCorrupt("malformed source failure code")
		}
		if (src.State == ControlPlaneStateFailed) != (src.FailureCode != "") {
			return cpCorrupt("failure code does not match source state")
		}
	}
	if got := cpDeriveRunState(run.Sources); got != run.State {
		return cpCorrupt("run state is not derivable from its sources")
	}

	createdAt, ok := cpParseStamp(run.CreatedAt)
	if !ok {
		return cpCorrupt("malformed run creation timestamp")
	}
	updatedAt, ok := cpParseStamp(run.UpdatedAt)
	if !ok {
		return cpCorrupt("malformed run update timestamp")
	}
	if updatedAt.Before(createdAt) {
		return cpCorrupt("run was updated before it was created")
	}

	// The portfolio digest, when present, must still derive from the exact
	// per-source plan digests currently on record. This is what makes an
	// approval digest a binding commitment rather than an opaque string.
	if run.PortfolioPlanDigest != "" {
		if !cpDigestRe.MatchString(run.PortfolioPlanDigest) {
			return cpCorrupt("malformed portfolio plan digest")
		}
		for i := range run.Sources {
			if run.Sources[i].PlanDigest == "" {
				return cpCorrupt("portfolio digest without a complete plan set")
			}
		}
		if cpPortfolioPlanDigest(run) != run.PortfolioPlanDigest {
			return cpCorrupt("portfolio plan digest does not bind its source plans")
		}
	}
	if r, ok := cpProgressRank[run.State]; ok && r >= cpProgressRank[ControlPlaneStateAwaitingApproval] {
		if run.PortfolioPlanDigest == "" {
			return cpCorrupt("approval-stage run without a portfolio plan digest")
		}
	}
	if run.ApprovalID != "" && !cpApprovalIDRe.MatchString(run.ApprovalID) {
		return cpCorrupt("malformed run approval id")
	}
	return nil
}

func cpValidateApprovals(snap *cpSnapshot, runs map[string]*ControlPlaneRun) error {
	byRun := make(map[string]*ControlPlaneApproval, len(snap.Approvals))
	seen := make(map[string]bool, len(snap.Approvals))
	for _, apr := range snap.Approvals {
		if apr == nil {
			return cpCorrupt("nil approval")
		}
		if !cpApprovalIDRe.MatchString(apr.ApprovalID) {
			return cpCorrupt("malformed approval id")
		}
		if seen[apr.ApprovalID] {
			return cpCorrupt("duplicate approval id")
		}
		seen[apr.ApprovalID] = true

		run, ok := runs[apr.RunID]
		if !ok {
			return cpCorrupt("approval references an unknown run")
		}
		if _, dup := byRun[apr.RunID]; dup {
			return cpCorrupt("more than one approval for a run")
		}
		byRun[apr.RunID] = apr

		if run.ApprovalID != apr.ApprovalID {
			return cpCorrupt("run and approval are not linked")
		}
		if !cpDigestRe.MatchString(apr.PlanDigest) || apr.PlanDigest != run.PortfolioPlanDigest {
			return cpCorrupt("approval digest does not match the run plan digest")
		}
		switch {
		case apr.Decision == "approve" && apr.ResultingState == ControlPlaneStateApproved:
		case apr.Decision == "reject" && apr.ResultingState == ControlPlaneStateCancelled:
		default:
			return cpCorrupt("approval decision and resulting state disagree")
		}
		if !cpIsBoundedName(apr.DecidedBy, cpMaxNameRunes, cpActorRe) {
			return cpCorrupt("malformed approval actor")
		}
		if _, ok := cpParseStamp(apr.DecidedAt); !ok {
			return cpCorrupt("malformed approval timestamp")
		}
		if apr.Reason != "" && !cpIsSafeText(apr.Reason, cpMaxReasonRunes) {
			return cpCorrupt("unsafe approval reason")
		}
	}
	for _, run := range snap.Runs {
		if run.ApprovalID == "" {
			continue
		}
		apr, ok := byRun[run.RunID]
		if !ok || apr.ApprovalID != run.ApprovalID {
			return cpCorrupt("run references a missing approval")
		}
	}
	return nil
}

func cpValidateEvents(snap *cpSnapshot, runs map[string]*ControlPlaneRun) error {
	seen := make(map[string]bool, len(snap.Events))
	perRun := make(map[string]int, len(runs))
	firstOfRun := make(map[string]bool, len(runs))
	var prevSeq uint64
	var prevStamp time.Time
	for i, ev := range snap.Events {
		if ev == nil {
			return cpCorrupt("nil event")
		}
		if !cpEventIDRe.MatchString(ev.EventID) {
			return cpCorrupt("malformed event id")
		}
		if seen[ev.EventID] {
			return cpCorrupt("duplicate event id")
		}
		seen[ev.EventID] = true

		if i > 0 && ev.Seq <= prevSeq {
			return cpCorrupt("event sequence is not strictly increasing")
		}
		if ev.Seq >= snap.NextSeq {
			return cpCorrupt("event sequence exceeds the snapshot cursor")
		}
		prevSeq = ev.Seq

		run, ok := runs[ev.RunID]
		if !ok {
			return cpCorrupt("event references an unknown run")
		}
		sourceScoped, known := cpEventSourceScoped[ev.EventType]
		if !known {
			return cpCorrupt("unknown event type")
		}
		if sourceScoped {
			if ev.SourceID == "" {
				return cpCorrupt("source event without a source")
			}
			if cpFindSource(run, ev.SourceID) == nil {
				return cpCorrupt("event references a source outside its run")
			}
		} else if ev.SourceID != "" {
			return cpCorrupt("portfolio event carries a source")
		}
		if !cpIsKnownState(ev.State) {
			return cpCorrupt("unknown event state")
		}
		if !cpIsSafeText(ev.Summary, cpMaxSummaryRunes) {
			return cpCorrupt("unsafe event summary")
		}
		if ev.EvidenceReferences == nil {
			return cpCorrupt("missing evidence reference list")
		}
		if len(ev.EvidenceReferences) > cpMaxEvidencePerEvt {
			return cpCorrupt("too many evidence references")
		}
		for _, ref := range ev.EvidenceReferences {
			if !cpArtifactIDRe.MatchString(ref.ArtifactID) {
				return cpCorrupt("malformed evidence artifact id")
			}
			if !cpEvidenceKinds[ref.Kind] {
				return cpCorrupt("unknown evidence kind")
			}
			if !cpDigestRe.MatchString(ref.Digest) {
				return cpCorrupt("malformed evidence digest")
			}
		}
		stamp, ok := cpParseStamp(ev.Timestamp)
		if !ok {
			return cpCorrupt("malformed event timestamp")
		}
		if i > 0 && stamp.Before(prevStamp) {
			return cpCorrupt("event timestamps are not monotonic")
		}
		prevStamp = stamp

		if !firstOfRun[ev.RunID] {
			if ev.EventType != "migration.created" {
				return cpCorrupt("run event log does not open with creation")
			}
			firstOfRun[ev.RunID] = true
		}
		perRun[ev.RunID]++
		if perRun[ev.RunID] > cpMaxEventsPerRun {
			return cpCorrupt("run event capacity exceeded")
		}
	}
	for runID := range runs {
		if !firstOfRun[runID] {
			return cpCorrupt("run has no creation event")
		}
	}
	return nil
}

// ---------------------------------------------------------------------------
// Durable store
// ---------------------------------------------------------------------------

// cpStore owns the snapshot and its file. Every exported operation takes mu
// for its whole duration, so reads never observe a half-applied mutation and
// concurrent writers serialise behind one durable write each.
type cpStore struct {
	mu   sync.Mutex
	path string
	dir  string
	snap *cpSnapshot
	now  func() time.Time
}

func cpOpenStore(statePath string) (*cpStore, error) {
	if strings.TrimSpace(statePath) == "" {
		return nil, errors.New("control plane: a state path is required")
	}
	abs, err := filepath.Abs(statePath)
	if err != nil {
		return nil, errors.New("control plane: state path cannot be resolved")
	}
	dir := filepath.Dir(abs)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, errors.New("control plane: state directory cannot be prepared")
	}
	s := &cpStore{path: abs, dir: dir, now: func() time.Time { return time.Now().UTC() }}

	raw, err := os.ReadFile(abs)
	switch {
	case err == nil:
		snap, derr := cpDecodeSnapshot(raw)
		if derr != nil {
			return nil, derr
		}
		s.snap = snap
	case errors.Is(err, os.ErrNotExist):
		s.snap = &cpSnapshot{
			SnapshotVersion: cpSnapshotVersion,
			SchemaVersion:   cpSchemaVersion,
			NextSeq:         1,
			Runs:            []*ControlPlaneRun{},
			Approvals:       []*ControlPlaneApproval{},
			Events:          []*ControlPlaneEvent{},
		}
		if _, werr := s.persist(s.snap); werr != nil {
			return nil, errors.New("control plane: initial state could not be written")
		}
	default:
		return nil, errors.New("control plane: state could not be read")
	}
	return s, nil
}

// cpDecodeSnapshot parses a snapshot strictly: unknown fields, trailing data
// and any integrity violation are refused rather than silently repaired.
func cpDecodeSnapshot(raw []byte) (*cpSnapshot, error) {
	dec := json.NewDecoder(strings.NewReader(string(raw)))
	dec.DisallowUnknownFields()
	var snap cpSnapshot
	if err := dec.Decode(&snap); err != nil {
		return nil, cpCorrupt("state is not a strict snapshot document")
	}
	if err := dec.Decode(new(struct{})); !errors.Is(err, io.EOF) {
		return nil, cpCorrupt("state carries trailing data")
	}
	if snap.Runs == nil {
		snap.Runs = []*ControlPlaneRun{}
	}
	if snap.Approvals == nil {
		snap.Approvals = []*ControlPlaneApproval{}
	}
	if snap.Events == nil {
		snap.Events = []*ControlPlaneEvent{}
	}
	if err := cpValidateSnapshot(&snap); err != nil {
		return nil, err
	}
	return &snap, nil
}

// persist writes snap atomically and durably: a fresh 0600 temp file in the
// same directory, fsync, rename, then an fsync of the parent directory so the
// rename itself survives a crash.
func (s *cpStore) persist(snap *cpSnapshot) (bool, error) {
	data, err := json.Marshal(snap)
	if err != nil {
		return false, err
	}
	tmp, err := os.CreateTemp(s.dir, ".control-plane-*.tmp")
	if err != nil {
		return false, err
	}
	name := tmp.Name()
	committed := false
	defer func() {
		if !committed {
			_ = os.Remove(name)
		}
	}()
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Close(); err != nil {
		return false, err
	}
	if err := os.Rename(name, s.path); err != nil {
		return false, err
	}
	committed = true

	d, err := os.Open(s.dir)
	if err != nil {
		return true, err
	}
	defer d.Close()
	return true, d.Sync()
}

// cloneForMutation returns a snapshot safe to mutate. Runs are copied because
// they change in place; events and approvals are immutable once appended, so
// only the slices are copied.
func (s *cpStore) cloneForMutation() *cpSnapshot {
	next := &cpSnapshot{
		SnapshotVersion: s.snap.SnapshotVersion,
		SchemaVersion:   s.snap.SchemaVersion,
		NextSeq:         s.snap.NextSeq,
		Runs:            make([]*ControlPlaneRun, len(s.snap.Runs)),
		Approvals:       append([]*ControlPlaneApproval{}, s.snap.Approvals...),
		Events:          append([]*ControlPlaneEvent{}, s.snap.Events...),
	}
	for i, r := range s.snap.Runs {
		next.Runs[i] = r.clone()
	}
	return next
}

// commit validates and durably writes next, and only then makes it visible.
// A failed write leaves the in-memory state exactly as it was.
func (s *cpStore) commit(next *cpSnapshot) error {
	if err := cpValidateSnapshot(next); err != nil {
		return cpErrInternal
	}
	renamed, err := s.persist(next)
	if renamed {
		s.snap = next
	}
	if err != nil {
		return cpErrInternal
	}
	return nil
}

// stamp returns the timestamp for a mutation, never moving backwards even if
// the wall clock does.
func (s *cpStore) stamp(next *cpSnapshot) string {
	t := s.now().UTC()
	if n := len(next.Events); n > 0 {
		if prev, ok := cpParseStamp(next.Events[n-1].Timestamp); ok && !t.After(prev) {
			t = prev.Add(time.Millisecond)
		}
	}
	return t.Format(cpTimeFormat)
}

// appendEvent records one immutable event in global order.
func (s *cpStore) appendEvent(next *cpSnapshot, run *ControlPlaneRun, sourceID, eventType, stamp, summary string, refs []ControlPlaneEvidence) error {
	scoped, known := cpEventSourceScoped[eventType]
	if !known || scoped != (sourceID != "") {
		return cpErrInternal
	}
	if !cpIsSafeText(summary, cpMaxSummaryRunes) {
		return cpErrInternal
	}
	count := 0
	for _, ev := range next.Events {
		if ev.RunID == run.RunID {
			count++
		}
	}
	if count >= cpMaxEventsPerRun {
		return cpErrEventLimit
	}
	if refs == nil {
		refs = []ControlPlaneEvidence{}
	}
	id, err := cpUniqueID(next, "evt_")
	if err != nil {
		return cpErrInternal
	}
	next.Events = append(next.Events, &ControlPlaneEvent{
		Seq:                next.NextSeq,
		EventID:            id,
		RunID:              run.RunID,
		SourceID:           sourceID,
		EventType:          eventType,
		Timestamp:          stamp,
		Summary:            summary,
		EvidenceReferences: refs,
		State:              run.State,
	})
	next.NextSeq++
	return nil
}

// cpUniqueID generates an identifier not already present in the snapshot.
func cpUniqueID(snap *cpSnapshot, prefix string) (string, error) {
	for attempt := 0; attempt < 8; attempt++ {
		id, err := cpRandomID(prefix, cpIDEntropyChars)
		if err != nil {
			return "", err
		}
		if !cpIDInUse(snap, id) {
			return id, nil
		}
	}
	return "", errors.New("control plane: identifier space exhausted")
}

// ---------------------------------------------------------------------------
// Store operations
// ---------------------------------------------------------------------------

// cpCreateRequest is the strict wire shape of a create request.
type cpCreateRequest struct {
	SchemaVersion string               `json:"schemaVersion"`
	PortfolioName string               `json:"portfolioName"`
	Sources       []cpSourceDescriptor `json:"sources"`
	RequestedBy   string               `json:"requestedBy"`
}

type cpSourceDescriptor struct {
	SourceID string `json:"sourceId"`
	Hostname string `json:"hostname"`
}

// cpApprovalRequest is the strict wire shape of an approval decision.
type cpApprovalRequest struct {
	SchemaVersion string `json:"schemaVersion"`
	PlanDigest    string `json:"planDigest"`
	Decision      string `json:"decision"`
	DecidedBy     string `json:"decidedBy"`
	Reason        string `json:"reason"`
}

// cpValidateSourceSet accepts only the three canonical pairs, each once.
func cpValidateSourceSet(in []cpSourceDescriptor) error {
	if len(in) != len(cpCanonicalSources) {
		return cpErrInvalidSources
	}
	seen := make(map[string]bool, len(in))
	for _, d := range in {
		host, ok := cpCanonicalHostname(d.SourceID)
		if !ok || host != d.Hostname || seen[d.SourceID] {
			return cpErrInvalidSources
		}
		seen[d.SourceID] = true
	}
	return nil
}

// CreateRun validates and durably records a new three-source portfolio.
func (s *cpStore) CreateRun(req *cpCreateRequest) (*ControlPlaneRun, error) {
	return s.createRunWithPrecommit(req, nil)
}

// createRunWithPrecommit permits trusted in-process adapters to durably bind
// metadata before the control-plane run becomes visible. A callback failure
// leaves no run; a later control-plane commit failure can leave only a safe
// dangling external binding, never an executable unowned run.
func (s *cpStore) createRunWithPrecommit(req *cpCreateRequest, beforeCommit func(*ControlPlaneRun) error) (*ControlPlaneRun, error) {
	if req.SchemaVersion != cpSchemaVersion {
		return nil, cpErrInvalidRequest
	}
	if !cpIsBoundedName(req.PortfolioName, cpMaxNameRunes, cpPortfolioNameRe) {
		return nil, cpErrInvalidRequest
	}
	if req.RequestedBy != "" && !cpIsBoundedName(req.RequestedBy, cpMaxNameRunes, cpActorRe) {
		return nil, cpErrInvalidRequest
	}
	if err := cpValidateSourceSet(req.Sources); err != nil {
		return nil, err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	for _, r := range s.snap.Runs {
		if r.PortfolioName == req.PortfolioName && !cpIsTerminalState(r.State) {
			return nil, cpErrPortfolioExists
		}
	}
	if len(s.snap.Runs) >= cpMaxRuns {
		return nil, cpErrCapacity
	}

	next := s.cloneForMutation()
	runID, err := cpUniqueID(next, "mig_")
	if err != nil {
		return nil, cpErrInternal
	}
	stamp := s.stamp(next)
	run := &ControlPlaneRun{
		RunID:         runID,
		PortfolioName: req.PortfolioName,
		State:         ControlPlaneStateCreated,
		Sources:       make([]ControlPlaneSource, 0, len(cpCanonicalSources)),
		RequestedBy:   req.RequestedBy,
		CreatedAt:     stamp,
		UpdatedAt:     stamp,
	}
	for _, c := range cpCanonicalSources {
		run.Sources = append(run.Sources, ControlPlaneSource{
			SourceID: c.SourceID,
			Hostname: c.Hostname,
			State:    ControlPlaneStateCreated,
		})
	}
	next.Runs = append(next.Runs, run)
	if err := s.appendEvent(next, run, "", "migration.created", stamp,
		"Portfolio created for the three legacy sources.", nil); err != nil {
		return nil, err
	}
	if beforeCommit != nil {
		if err := beforeCommit(run.clone()); err != nil {
			return nil, err
		}
	}
	if err := s.commit(next); err != nil {
		return nil, err
	}
	return run.clone(), nil
}

// GetRun returns a defensive copy of one portfolio.
func (s *cpStore) GetRun(runID string) (*ControlPlaneRun, error) {
	if !cpRunIDRe.MatchString(runID) {
		return nil, cpErrNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	run := cpFindRun(s.snap, runID)
	if run == nil {
		return nil, cpErrNotFound
	}
	return run.clone(), nil
}

// Approval returns a defensive copy of the durable decision for one run.
func (s *cpStore) Approval(runID string) (*ControlPlaneApproval, error) {
	if !cpRunIDRe.MatchString(runID) {
		return nil, cpErrNotFound
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, approval := range s.snap.Approvals {
		if approval.RunID == runID {
			out := *approval
			return &out, nil
		}
	}
	return nil, cpErrNotFound
}

// EventsAfter returns up to limit stored events for a run, in stored order,
// strictly after the event named by cursor. An unrecognised cursor is an
// error: the stream never silently skips events a client has not seen.
func (s *cpStore) EventsAfter(runID, cursor string, limit int) ([]*ControlPlaneEvent, bool, error) {
	if !cpRunIDRe.MatchString(runID) {
		return nil, false, cpErrNotFound
	}
	if cursor != "" && !cpEventIDRe.MatchString(cursor) {
		return nil, false, cpErrInvalidCursor
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if cpFindRun(s.snap, runID) == nil {
		return nil, false, cpErrNotFound
	}
	var all []*ControlPlaneEvent
	for _, ev := range s.snap.Events {
		if ev.RunID == runID {
			all = append(all, ev)
		}
	}
	if cursor != "" {
		idx := -1
		for i, ev := range all {
			if ev.EventID == cursor {
				idx = i
				break
			}
		}
		if idx < 0 {
			return nil, false, cpErrUnknownCursor
		}
		all = all[idx+1:]
	}
	truncated := false
	if limit > 0 && len(all) > limit {
		all, truncated = all[:limit], true
	}
	out := make([]*ControlPlaneEvent, len(all))
	for i, ev := range all {
		out[i] = ev.clone()
	}
	return out, truncated, nil
}

// ControlPlaneSourceUpdate carries the evidence and counters attached to one
// source transition. Counters are optional and may only move forwards.
type ControlPlaneSourceUpdate struct {
	ArtifactID          string
	Digest              string
	SecondaryArtifactID string
	SecondaryDigest     string
	RecordsRead         *int64
	RecordsWritten      *int64
	RecordsRejected     *int64
}

// cpAdvanceSteps is the frozen per-source sequence reachable through
// AdvanceSource, keyed by the state being entered. awaiting_approval,
// approved, cancelled and failed are deliberately absent: they are reached
// only through the approval gate, the approval decision, or FailSource.
var cpAdvanceSteps = map[ControlPlaneState]struct {
	From                  ControlPlaneState
	EventType             string
	EvidenceKind          string
	SecondaryEvidenceKind string
	Summary               string
}{
	ControlPlaneStateInventorying: {ControlPlaneStateCreated, "source.inventory.started", "", "", "inventory started."},
	ControlPlaneStateRedacting:    {ControlPlaneStateInventorying, "source.inventory.completed", "source_manifest", "", "inventory completed and source manifest recorded."},
	ControlPlaneStatePlanning:     {ControlPlaneStateRedacting, "source.redaction.completed", "redaction_report", "", "redaction report recorded."},
	ControlPlaneStateExecuting:    {ControlPlaneStateApproved, "source.execution.started", "", "", "execution started."},
	ControlPlaneStateVerifying:    {ControlPlaneStateExecuting, "source.execution.completed", "dataflow_job", "bigquery_table", "execution completed."},
	ControlPlaneStateCompleted:    {ControlPlaneStateVerifying, "source.verification.completed", "reconciliation", "audit_log", "verification completed."},
}

// AdvanceSource moves one source to the next state in the frozen sequence,
// attaching the evidence that step requires. Any other transition, and any
// transition on a terminal portfolio, fails closed.
func (s *cpStore) AdvanceSource(runID, sourceID string, to ControlPlaneState, upd ControlPlaneSourceUpdate) (*ControlPlaneRun, error) {
	step, ok := cpAdvanceSteps[to]
	if !ok {
		return nil, cpErrInvalidTransition
	}
	if _, ok := cpCanonicalHostname(sourceID); !ok {
		return nil, cpErrNotFound
	}
	if step.EvidenceKind == "" {
		if upd.ArtifactID != "" || upd.Digest != "" || upd.SecondaryArtifactID != "" || upd.SecondaryDigest != "" {
			return nil, cpErrInvalidRequest
		}
	} else {
		if !cpArtifactIDRe.MatchString(upd.ArtifactID) || !cpDigestRe.MatchString(upd.Digest) {
			return nil, cpErrInvalidRequest
		}
		hasSecondary := upd.SecondaryArtifactID != "" || upd.SecondaryDigest != ""
		if hasSecondary && (step.SecondaryEvidenceKind == "" || !cpArtifactIDRe.MatchString(upd.SecondaryArtifactID) || !cpDigestRe.MatchString(upd.SecondaryDigest)) {
			return nil, cpErrInvalidRequest
		}
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	next, run, err := s.mutableRun(runID)
	if err != nil {
		return nil, err
	}
	src := cpFindSource(run, sourceID)
	if src == nil {
		return nil, cpErrNotFound
	}
	if src.State != step.From {
		return nil, cpErrInvalidTransition
	}
	if err := cpApplyCounters(src, upd); err != nil {
		return nil, err
	}
	if step.EvidenceKind == "source_manifest" {
		src.RecordDigest = upd.Digest
	}
	src.State = to

	before := run.State
	run.State = cpDeriveRunState(run.Sources)
	stamp := s.stamp(next)
	run.UpdatedAt = stamp

	var refs []ControlPlaneEvidence
	if step.EvidenceKind != "" {
		refs = []ControlPlaneEvidence{{ArtifactID: upd.ArtifactID, Kind: step.EvidenceKind, Digest: upd.Digest}}
		if upd.SecondaryArtifactID != "" {
			refs = append(refs, ControlPlaneEvidence{ArtifactID: upd.SecondaryArtifactID, Kind: step.SecondaryEvidenceKind, Digest: upd.SecondaryDigest})
		}
	}
	summary := cpSourceLabel(sourceID) + " " + step.Summary
	if err := s.appendEvent(next, run, sourceID, step.EventType, stamp, summary, refs); err != nil {
		return nil, err
	}
	if before != ControlPlaneStateCompleted && run.State == ControlPlaneStateCompleted {
		if err := s.appendEvent(next, run, "", "migration.completed", stamp,
			"All three sources completed verification.", nil); err != nil {
			return nil, err
		}
	}
	if err := s.commit(next); err != nil {
		return nil, err
	}
	return run.clone(), nil
}

func cpApplyCounters(src *ControlPlaneSource, upd ControlPlaneSourceUpdate) error {
	for _, c := range []struct {
		in  *int64
		out *int64
	}{
		{upd.RecordsRead, &src.RecordsRead},
		{upd.RecordsWritten, &src.RecordsWritten},
		{upd.RecordsRejected, &src.RecordsRejected},
	} {
		if c.in == nil {
			continue
		}
		if *c.in < 0 || *c.in < *c.out {
			return cpErrInvalidRequest
		}
		*c.out = *c.in
	}
	return nil
}

// mutableRun returns a mutable snapshot and run, refusing terminal portfolios.
// The caller must already hold s.mu.
func (s *cpStore) mutableRun(runID string) (*cpSnapshot, *ControlPlaneRun, error) {
	if !cpRunIDRe.MatchString(runID) {
		return nil, nil, cpErrNotFound
	}
	if cpFindRun(s.snap, runID) == nil {
		return nil, nil, cpErrNotFound
	}
	next := s.cloneForMutation()
	run := cpFindRun(next, runID)
	if cpIsTerminalState(run.State) {
		return nil, nil, cpErrTerminal
	}
	return next, run, nil
}

// AttachSourcePlan binds one source's transform plan digest while that source
// is planning. The binding is immutable once written.
func (s *cpStore) AttachSourcePlan(runID, sourceID, artifactID, planDigest string) (*ControlPlaneRun, error) {
	if _, ok := cpCanonicalHostname(sourceID); !ok {
		return nil, cpErrNotFound
	}
	if !cpArtifactIDRe.MatchString(artifactID) {
		return nil, cpErrInvalidRequest
	}
	if !cpDigestRe.MatchString(planDigest) {
		return nil, cpErrInvalidDigest
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	next, run, err := s.mutableRun(runID)
	if err != nil {
		return nil, err
	}
	src := cpFindSource(run, sourceID)
	if src == nil {
		return nil, cpErrNotFound
	}
	if src.State != ControlPlaneStatePlanning {
		return nil, cpErrInvalidTransition
	}
	if src.PlanDigest != "" {
		return nil, cpErrInvalidTransition
	}
	src.PlanDigest = planDigest
	src.PlanArtifactID = artifactID
	run.UpdatedAt = s.stamp(next)
	if err := s.commit(next); err != nil {
		return nil, err
	}
	return run.clone(), nil
}

// EnterAwaitingApproval closes planning for the whole portfolio. It requires
// all three sources to be planning with a bound plan digest, derives the
// portfolio plan digest from exactly those plans, and opens the approval gate.
func (s *cpStore) EnterAwaitingApproval(runID string) (*ControlPlaneRun, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	next, run, err := s.mutableRun(runID)
	if err != nil {
		return nil, err
	}
	for i := range run.Sources {
		if run.Sources[i].State != ControlPlaneStatePlanning || run.Sources[i].PlanDigest == "" {
			return nil, cpErrInvalidTransition
		}
	}
	for i := range run.Sources {
		run.Sources[i].State = ControlPlaneStateAwaitingApproval
	}
	run.State = cpDeriveRunState(run.Sources)
	run.PortfolioPlanDigest = cpPortfolioPlanDigest(run)
	if run.PortfolioPlanDigest == "" {
		return nil, cpErrInternal
	}
	stamp := s.stamp(next)
	run.UpdatedAt = stamp

	for _, c := range cpCanonicalSources {
		src := cpFindSource(run, c.SourceID)
		refs := []ControlPlaneEvidence{{
			ArtifactID: src.PlanArtifactID,
			Kind:       "transform_plan",
			Digest:     src.PlanDigest,
		}}
		summary := c.Label + " transform plan is ready for portfolio approval."
		if err := s.appendEvent(next, run, c.SourceID, "source.plan.ready", stamp, summary, refs); err != nil {
			return nil, err
		}
	}
	if err := s.appendEvent(next, run, "", "portfolio.awaiting_approval", stamp,
		"All three source plans are ready for one portfolio decision.", nil); err != nil {
		return nil, err
	}
	if err := s.commit(next); err != nil {
		return nil, err
	}
	return run.clone(), nil
}

// FailSource records a terminal failure for one source, which fails the whole
// portfolio.
func (s *cpStore) FailSource(runID, sourceID, failureCode string) (*ControlPlaneRun, error) {
	if _, ok := cpCanonicalHostname(sourceID); !ok {
		return nil, cpErrNotFound
	}
	if !cpFailureCodeRe.MatchString(failureCode) {
		return nil, cpErrInvalidRequest
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	next, run, err := s.mutableRun(runID)
	if err != nil {
		return nil, err
	}
	src := cpFindSource(run, sourceID)
	if src == nil {
		return nil, cpErrNotFound
	}
	if cpIsTerminalState(src.State) {
		return nil, cpErrInvalidTransition
	}
	src.State = ControlPlaneStateFailed
	src.FailureCode = failureCode
	run.State = cpDeriveRunState(run.Sources)
	run.FailureCode = failureCode
	stamp := s.stamp(next)
	run.UpdatedAt = stamp

	summary := cpSourceLabel(sourceID) + " reported failure code " + failureCode + "."
	if err := s.appendEvent(next, run, sourceID, "source.failed", stamp, summary, nil); err != nil {
		return nil, err
	}
	if err := s.appendEvent(next, run, "", "migration.failed", stamp,
		"Portfolio failed because a source failed.", nil); err != nil {
		return nil, err
	}
	if err := s.commit(next); err != nil {
		return nil, err
	}
	return run.clone(), nil
}

// Decide records the single immutable portfolio approval decision. The digest
// presented must equal the current portfolio plan digest exactly; a stale or
// replayed decision conflicts rather than overwriting.
func (s *cpStore) Decide(runID string, req *cpApprovalRequest) (*ControlPlaneApproval, error) {
	if req.SchemaVersion != cpSchemaVersion {
		return nil, cpErrInvalidRequest
	}
	if req.Decision != "approve" && req.Decision != "reject" {
		return nil, cpErrInvalidRequest
	}
	if !cpIsBoundedName(req.DecidedBy, cpMaxNameRunes, cpActorRe) {
		return nil, cpErrInvalidRequest
	}
	if req.Reason != "" && !cpIsSafeText(req.Reason, cpMaxReasonRunes) {
		return nil, cpErrInvalidRequest
	}
	if !cpDigestRe.MatchString(req.PlanDigest) {
		return nil, cpErrInvalidDigest
	}
	if !cpRunIDRe.MatchString(runID) {
		return nil, cpErrNotFound
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	current := cpFindRun(s.snap, runID)
	if current == nil {
		return nil, cpErrNotFound
	}
	// Replay and second decisions are rejected before state is consulted, so
	// a repeated request always reports the same conflict.
	if current.ApprovalID != "" {
		return nil, cpErrAlreadyDecided
	}
	if current.State != ControlPlaneStateAwaitingApproval || current.PortfolioPlanDigest == "" {
		return nil, cpErrNotAwaitingApproval
	}
	if subtle.ConstantTimeCompare([]byte(req.PlanDigest), []byte(current.PortfolioPlanDigest)) != 1 {
		return nil, cpErrStaleDigest
	}

	next := s.cloneForMutation()
	run := cpFindRun(next, runID)
	aprID, err := cpUniqueID(next, "apr_")
	if err != nil {
		return nil, cpErrInternal
	}
	stamp := s.stamp(next)

	resulting := ControlPlaneStateApproved
	if req.Decision == "reject" {
		resulting = ControlPlaneStateCancelled
	}
	for i := range run.Sources {
		run.Sources[i].State = resulting
	}
	run.State = cpDeriveRunState(run.Sources)
	run.UpdatedAt = stamp
	run.ApprovalID = aprID

	apr := &ControlPlaneApproval{
		ApprovalID:     aprID,
		RunID:          run.RunID,
		PlanDigest:     run.PortfolioPlanDigest,
		Decision:       req.Decision,
		ResultingState: resulting,
		DecidedBy:      req.DecidedBy,
		DecidedAt:      stamp,
		Reason:         req.Reason,
	}
	next.Approvals = append(next.Approvals, apr)

	if req.Decision == "approve" {
		if err := s.appendEvent(next, run, "", "portfolio.approved", stamp,
			"Portfolio plan digest approved.", nil); err != nil {
			return nil, err
		}
	} else {
		if err := s.appendEvent(next, run, "", "portfolio.rejected", stamp,
			"Portfolio plan digest rejected.", nil); err != nil {
			return nil, err
		}
		if err := s.appendEvent(next, run, "", "migration.cancelled", stamp,
			"Portfolio cancelled after rejection.", nil); err != nil {
			return nil, err
		}
	}
	if err := s.commit(next); err != nil {
		return nil, err
	}
	out := *apr
	return &out, nil
}

func cpIDInUse(snap *cpSnapshot, id string) bool {
	for _, r := range snap.Runs {
		if r.RunID == id {
			return true
		}
	}
	for _, a := range snap.Approvals {
		if a.ApprovalID == id {
			return true
		}
	}
	for _, e := range snap.Events {
		if e.EventID == id {
			return true
		}
	}
	return false
}

// ---------------------------------------------------------------------------
// Wire projections
// ---------------------------------------------------------------------------

// cpRunBody is the closed contract migration-run document. Internal bindings
// (requester, approval id, record digest, plan artifact id) are omitted.
type cpRunBody struct {
	SchemaVersion       string            `json:"schemaVersion"`
	RunID               string            `json:"runId"`
	PortfolioName       string            `json:"portfolioName"`
	State               ControlPlaneState `json:"state"`
	Sources             []cpSourceBody    `json:"sources"`
	PortfolioPlanDigest string            `json:"portfolioPlanDigest,omitempty"`
	CreatedAt           string            `json:"createdAt"`
	UpdatedAt           string            `json:"updatedAt"`
	FailureCode         string            `json:"failureCode,omitempty"`
}

type cpSourceBody struct {
	SourceID        string            `json:"sourceId"`
	Hostname        string            `json:"hostname"`
	State           ControlPlaneState `json:"state"`
	RecordsRead     int64             `json:"recordsRead"`
	RecordsWritten  int64             `json:"recordsWritten"`
	RecordsRejected int64             `json:"recordsRejected"`
	PlanDigest      string            `json:"planDigest,omitempty"`
	FailureCode     string            `json:"failureCode,omitempty"`
}

func cpRunToBody(run *ControlPlaneRun) cpRunBody {
	body := cpRunBody{
		SchemaVersion:       cpSchemaVersion,
		RunID:               run.RunID,
		PortfolioName:       run.PortfolioName,
		State:               run.State,
		Sources:             make([]cpSourceBody, 0, len(run.Sources)),
		PortfolioPlanDigest: run.PortfolioPlanDigest,
		CreatedAt:           run.CreatedAt,
		UpdatedAt:           run.UpdatedAt,
		FailureCode:         run.FailureCode,
	}
	for _, s := range run.Sources {
		body.Sources = append(body.Sources, cpSourceBody{
			SourceID:        s.SourceID,
			Hostname:        s.Hostname,
			State:           s.State,
			RecordsRead:     s.RecordsRead,
			RecordsWritten:  s.RecordsWritten,
			RecordsRejected: s.RecordsRejected,
			PlanDigest:      s.PlanDigest,
			FailureCode:     s.FailureCode,
		})
	}
	return body
}

// cpEventBody is the closed contract sse-event document.
type cpEventBody struct {
	SchemaVersion      string                 `json:"schemaVersion"`
	EventID            string                 `json:"eventId"`
	RunID              string                 `json:"runId"`
	SourceID           string                 `json:"sourceId,omitempty"`
	EventType          string                 `json:"eventType"`
	Timestamp          string                 `json:"timestamp"`
	Summary            string                 `json:"summary"`
	EvidenceReferences []ControlPlaneEvidence `json:"evidenceReferences"`
	State              ControlPlaneState      `json:"state"`
}

func cpEventToBody(ev *ControlPlaneEvent) cpEventBody {
	refs := ev.EvidenceReferences
	if refs == nil {
		refs = []ControlPlaneEvidence{}
	}
	return cpEventBody{
		SchemaVersion:      cpSchemaVersion,
		EventID:            ev.EventID,
		RunID:              ev.RunID,
		SourceID:           ev.SourceID,
		EventType:          ev.EventType,
		Timestamp:          ev.Timestamp,
		Summary:            ev.Summary,
		EvidenceReferences: refs,
		State:              ev.State,
	}
}

// cpApprovalBody is the closed contract approval-response document. The
// caller-supplied reason is stored but deliberately never echoed.
type cpApprovalBody struct {
	SchemaVersion  string            `json:"schemaVersion"`
	ApprovalID     string            `json:"approvalId"`
	RunID          string            `json:"runId"`
	PlanDigest     string            `json:"planDigest"`
	Decision       string            `json:"decision"`
	ResultingState ControlPlaneState `json:"resultingState"`
	DecidedBy      string            `json:"decidedBy"`
	DecidedAt      string            `json:"decidedAt"`
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

// ControlPlaneHandler serves the frozen migration control-plane API and
// exposes the orchestration operations that advance a portfolio.
type ControlPlaneHandler struct {
	store *cpStore
	mux   *http.ServeMux
	// expectedAuth is the SHA-256 of the one acceptable Authorization header
	// value. Hashing keeps the comparison constant time and independent of
	// the presented header's length.
	expectedAuth [sha256.Size]byte
}

// NewControlPlaneHandler builds a durable, authenticated control-plane
// handler backed by the snapshot at statePath. An empty bearer token, or one
// that cannot appear verbatim in a header, is a configuration error.
func NewControlPlaneHandler(statePath, bearerToken string) (http.Handler, error) {
	if bearerToken == "" {
		return nil, errors.New("control plane: a bearer token is required")
	}
	for i := 0; i < len(bearerToken); i++ {
		if bearerToken[i] <= 0x20 || bearerToken[i] >= 0x7f {
			return nil, errors.New("control plane: the bearer token must be printable ASCII without spaces")
		}
	}
	store, err := cpOpenStore(statePath)
	if err != nil {
		return nil, err
	}
	h := &ControlPlaneHandler{
		store:        store,
		mux:          http.NewServeMux(),
		expectedAuth: sha256.Sum256([]byte("Bearer " + bearerToken)),
	}
	h.mux.HandleFunc("/api/v1/migrations", h.handleCreate)
	h.mux.HandleFunc("/api/v1/migrations/{run_id}", h.handleGet)
	h.mux.HandleFunc("/api/v1/migrations/{run_id}/events", h.handleEvents)
	h.mux.HandleFunc("/api/v1/migrations/{run_id}/approval", h.handleApproval)
	h.mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		cpWriteProblem(w, cpErrNotFound)
	})
	return h, nil
}

// ServeHTTP authenticates before routing, so an unauthenticated caller cannot
// distinguish a real path from a missing one.
func (h *ControlPlaneHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if !h.authorized(r) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		cpWriteProblem(w, cpErrUnauthorized)
		return
	}
	h.mux.ServeHTTP(w, r)
}

// authorized requires exactly one Authorization header whose entire value
// equals "Bearer " + the configured token, compared in constant time.
func (h *ControlPlaneHandler) authorized(r *http.Request) bool {
	values := r.Header.Values("Authorization")
	if len(values) != 1 {
		return false
	}
	got := sha256.Sum256([]byte(values[0]))
	return subtle.ConstantTimeCompare(got[:], h.expectedAuth[:]) == 1
}

func cpRequireMethod(w http.ResponseWriter, r *http.Request, method string) bool {
	if r.Method == method {
		return true
	}
	w.Header().Set("Allow", method)
	cpWriteProblem(w, cpErrMethodNotAllowed)
	return false
}

// cpIsJSONContentType accepts application/json, optionally with a UTF-8
// charset parameter, and nothing else.
func cpIsJSONContentType(v string) bool {
	mt, params, err := mime.ParseMediaType(v)
	if err != nil || mt != "application/json" {
		return false
	}
	if cs, ok := params["charset"]; ok && !strings.EqualFold(cs, "utf-8") && !strings.EqualFold(cs, "utf8") {
		return false
	}
	return true
}

// cpDecodeBody enforces the media type, the body limit, and a single strict
// JSON document with no unknown fields.
func cpDecodeBody(w http.ResponseWriter, r *http.Request, dst any) error {
	if len(r.Header.Values("Content-Type")) != 1 || !cpIsJSONContentType(r.Header.Get("Content-Type")) {
		return cpErrUnsupportedMedia
	}
	r.Body = http.MaxBytesReader(w, r.Body, cpMaxRequestBody)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return cpBodyFault(err)
	}
	if err := dec.Decode(new(struct{})); !errors.Is(err, io.EOF) {
		return cpBodyFault(err)
	}
	return nil
}

func cpBodyFault(err error) error {
	var tooLarge *http.MaxBytesError
	if errors.As(err, &tooLarge) {
		return cpErrPayloadTooLarge
	}
	return cpErrMalformedBody
}

func cpWriteJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(true)
	_ = enc.Encode(body)
}

func (h *ControlPlaneHandler) handleCreate(w http.ResponseWriter, r *http.Request) {
	if !cpRequireMethod(w, r, http.MethodPost) {
		return
	}
	var req cpCreateRequest
	if err := cpDecodeBody(w, r, &req); err != nil {
		cpWriteProblem(w, err)
		return
	}
	run, err := h.store.CreateRun(&req)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	w.Header().Set("Location", "/api/v1/migrations/"+run.RunID)
	cpWriteJSON(w, http.StatusAccepted, cpRunToBody(run))
}

func (h *ControlPlaneHandler) handleGet(w http.ResponseWriter, r *http.Request) {
	if !cpRequireMethod(w, r, http.MethodGet) {
		return
	}
	run, err := h.store.GetRun(r.PathValue("run_id"))
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	cpWriteJSON(w, http.StatusOK, cpRunToBody(run))
}

func (h *ControlPlaneHandler) handleApproval(w http.ResponseWriter, r *http.Request) {
	if !cpRequireMethod(w, r, http.MethodPost) {
		return
	}
	var req cpApprovalRequest
	if err := cpDecodeBody(w, r, &req); err != nil {
		cpWriteProblem(w, err)
		return
	}
	apr, err := h.store.Decide(r.PathValue("run_id"), &req)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	cpWriteJSON(w, http.StatusOK, cpApprovalBody{
		SchemaVersion:  cpSchemaVersion,
		ApprovalID:     apr.ApprovalID,
		RunID:          apr.RunID,
		PlanDigest:     apr.PlanDigest,
		Decision:       apr.Decision,
		ResultingState: apr.ResultingState,
		DecidedBy:      apr.DecidedBy,
		DecidedAt:      apr.DecidedAt,
	})
}

// handleEvents replays the stored event log as SSE. The replay is bounded;
// when it is truncated the stream simply ends, and the client resumes from the
// last identifier it received.
func (h *ControlPlaneHandler) handleEvents(w http.ResponseWriter, r *http.Request) {
	if !cpRequireMethod(w, r, http.MethodGet) {
		return
	}
	if len(r.Header.Values("Last-Event-ID")) > 1 {
		cpWriteProblem(w, cpErrInvalidCursor)
		return
	}
	events, _, err := h.store.EventsAfter(r.PathValue("run_id"), r.Header.Get("Last-Event-ID"), cpMaxSSEReplay)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	flusher, _ := w.(http.Flusher)
	fmt.Fprintf(w, "retry: %d\n\n", cpSSERetryMillis)
	if flusher != nil {
		flusher.Flush()
	}
	for _, ev := range events {
		select {
		case <-r.Context().Done():
			return
		default:
		}
		// Marshalling escapes every newline and markup character, so neither
		// a summary nor an identifier can forge SSE framing.
		payload, merr := json.Marshal(cpEventToBody(ev))
		if merr != nil {
			return
		}
		fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n", ev.EventID, ev.EventType, payload)
		if flusher != nil {
			flusher.Flush()
		}
	}
}

// ---------------------------------------------------------------------------
// Orchestration surface
// ---------------------------------------------------------------------------

// AdvanceSource moves one source to the next state in the frozen sequence.
func (h *ControlPlaneHandler) AdvanceSource(runID, sourceID string, to ControlPlaneState, upd ControlPlaneSourceUpdate) (*ControlPlaneRun, error) {
	return h.store.AdvanceSource(runID, sourceID, to, upd)
}

// AttachSourcePlan binds a transform plan digest to a planning source.
func (h *ControlPlaneHandler) AttachSourcePlan(runID, sourceID, artifactID, planDigest string) (*ControlPlaneRun, error) {
	return h.store.AttachSourcePlan(runID, sourceID, artifactID, planDigest)
}

// EnterAwaitingApproval opens the single portfolio approval gate.
func (h *ControlPlaneHandler) EnterAwaitingApproval(runID string) (*ControlPlaneRun, error) {
	return h.store.EnterAwaitingApproval(runID)
}

// FailSource records a terminal source failure.
func (h *ControlPlaneHandler) FailSource(runID, sourceID, failureCode string) (*ControlPlaneRun, error) {
	return h.store.FailSource(runID, sourceID, failureCode)
}

// Run returns a copy of one portfolio.
func (h *ControlPlaneHandler) Run(runID string) (*ControlPlaneRun, error) {
	return h.store.GetRun(runID)
}

// Approval returns the immutable recorded portfolio decision.
func (h *ControlPlaneHandler) Approval(runID string) (*ControlPlaneApproval, error) {
	return h.store.Approval(runID)
}

// Events returns a copy of one portfolio's stored events, in order.
func (h *ControlPlaneHandler) Events(runID string) ([]*ControlPlaneEvent, error) {
	events, _, err := h.store.EventsAfter(runID, "", 0)
	return events, err
}
