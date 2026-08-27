package main

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
)

const (
	orchestratorTokenEnv      = "MISSION_CONTROL_ORCHESTRATOR_TOKEN"
	orchestratorPath          = "/internal/v1/orchestration"
	orchestratorApprovalPath  = "/internal/v1/approvals/"
	orchestratorMaxBody       = 8 << 10
	orchestratorMaxTokenBytes = 512
)

var (
	errOrchestratorConfiguration = errors.New("orchestrator bridge configuration is incomplete")
	orchestratorErrLoopback      = &cpFault{
		Status: http.StatusForbidden,
		Slug:   "loopback-required",
		Title:  "Loopback connection required",
		Detail: "The orchestration endpoint accepts connections from this host only.",
	}
)

type orchestratorTarget interface {
	AdvanceSource(string, string, ControlPlaneState, ControlPlaneSourceUpdate) (*ControlPlaneRun, error)
	AttachSourcePlan(string, string, string, string) (*ControlPlaneRun, error)
	EnterAwaitingApproval(string) (*ControlPlaneRun, error)
	FailSource(string, string, string) (*ControlPlaneRun, error)
	Approval(string) (*ControlPlaneApproval, error)
}

// orchestratorBridgeHandler is a separately authenticated, loopback-only
// bridge from the local Python workflow into the existing durable event store.
// It deliberately exposes no create, approval, arbitrary-event, or evidence
// insertion primitive.
type orchestratorBridgeHandler struct {
	target       orchestratorTarget
	expectedAuth [sha256.Size]byte
}

type orchestratorRequest struct {
	SchemaVersion       string             `json:"schemaVersion"`
	Action              string             `json:"action"`
	RunID               string             `json:"runId"`
	SourceID            *string            `json:"sourceId,omitempty"`
	State               *ControlPlaneState `json:"state,omitempty"`
	ArtifactID          *string            `json:"artifactId,omitempty"`
	Digest              *string            `json:"digest,omitempty"`
	SecondaryArtifactID *string            `json:"secondaryArtifactId,omitempty"`
	SecondaryDigest     *string            `json:"secondaryDigest,omitempty"`
	FailureCode         *string            `json:"failureCode,omitempty"`
	RecordsRead         *int64             `json:"recordsRead,omitempty"`
	RecordsWritten      *int64             `json:"recordsWritten,omitempty"`
	RecordsRejected     *int64             `json:"recordsRejected,omitempty"`
}

var orchestratorFields = map[string]bool{
	"schemaVersion":       true,
	"action":              true,
	"runId":               true,
	"sourceId":            true,
	"state":               true,
	"artifactId":          true,
	"digest":              true,
	"secondaryArtifactId": true,
	"secondaryDigest":     true,
	"failureCode":         true,
	"recordsRead":         true,
	"recordsWritten":      true,
	"recordsRejected":     true,
}

func validOrchestratorToken(token string) bool {
	if token == "" || len(token) > orchestratorMaxTokenBytes {
		return false
	}
	for i := 0; i < len(token); i++ {
		if token[i] <= 0x20 || token[i] >= 0x7f {
			return false
		}
	}
	return true
}

func newOrchestratorBridgeHandler(target orchestratorTarget, bearerToken string) (http.Handler, error) {
	if target == nil || !validOrchestratorToken(bearerToken) {
		return nil, errOrchestratorConfiguration
	}
	return &orchestratorBridgeHandler{
		target:       target,
		expectedAuth: sha256.Sum256([]byte("Bearer " + bearerToken)),
	}, nil
}

// configuredOrchestratorBridge leaves the route absent unless its separate
// credential is explicitly configured. A configured bridge without the
// durable control plane fails startup rather than silently weakening the gate.
func configuredOrchestratorBridge(controlPlane http.Handler) (http.Handler, error) {
	token := os.Getenv(orchestratorTokenEnv)
	if token == "" {
		return nil, nil
	}
	publicToken := os.Getenv("MISSION_CONTROL_API_TOKEN")
	if publicToken == "" {
		return nil, errOrchestratorConfiguration
	}
	internalDigest := sha256.Sum256([]byte(token))
	publicDigest := sha256.Sum256([]byte(publicToken))
	if subtle.ConstantTimeCompare(internalDigest[:], publicDigest[:]) == 1 {
		return nil, errOrchestratorConfiguration
	}
	target, ok := controlPlane.(*ControlPlaneHandler)
	if !ok || target == nil {
		return nil, errOrchestratorConfiguration
	}
	return newOrchestratorBridgeHandler(target, token)
}

func (h *orchestratorBridgeHandler) authorized(r *http.Request) bool {
	values := r.Header.Values("Authorization")
	if len(values) != 1 {
		return false
	}
	got := sha256.Sum256([]byte(values[0]))
	return subtle.ConstantTimeCompare(got[:], h.expectedAuth[:]) == 1
}

func (h *orchestratorBridgeHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Referrer-Policy", "no-referrer")
	if !h.authorized(r) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		cpWriteProblem(w, cpErrUnauthorized)
		return
	}
	if !isLoopbackRemoteAddr(r.RemoteAddr) {
		cpWriteProblem(w, orchestratorErrLoopback)
		return
	}
	if strings.HasPrefix(r.URL.Path, orchestratorApprovalPath) {
		h.handleApprovalRead(w, r)
		return
	}
	if r.URL.Path != orchestratorPath {
		cpWriteProblem(w, cpErrNotFound)
		return
	}
	if !cpRequireMethod(w, r, http.MethodPost) {
		return
	}

	req, fields, err := decodeOrchestratorRequest(w, r)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	if err := validateOrchestratorRequest(req, fields); err != nil {
		cpWriteProblem(w, err)
		return
	}

	run, err := h.apply(req)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	cpWriteJSON(w, http.StatusOK, cpRunToBody(run))
}

func (h *orchestratorBridgeHandler) handleApprovalRead(w http.ResponseWriter, r *http.Request) {
	if !cpRequireMethod(w, r, http.MethodGet) {
		return
	}
	runID := strings.TrimPrefix(r.URL.Path, orchestratorApprovalPath)
	if !cpRunIDRe.MatchString(runID) || strings.Contains(runID, "/") {
		cpWriteProblem(w, cpErrNotFound)
		return
	}
	approval, err := h.target.Approval(runID)
	if err != nil {
		cpWriteProblem(w, err)
		return
	}
	cpWriteJSON(w, http.StatusOK, cpApprovalBody{
		SchemaVersion:  cpSchemaVersion,
		ApprovalID:     approval.ApprovalID,
		RunID:          approval.RunID,
		PlanDigest:     approval.PlanDigest,
		Decision:       approval.Decision,
		ResultingState: approval.ResultingState,
		DecidedBy:      approval.DecidedBy,
		DecidedAt:      approval.DecidedAt,
	})
}

// decodeOrchestratorRequest accepts exactly one bounded JSON object, rejects
// duplicate and unknown fields, and retains key presence for action-specific
// shape checks. The bridge has no nested or free-form request values.
func decodeOrchestratorRequest(w http.ResponseWriter, r *http.Request) (*orchestratorRequest, map[string]bool, error) {
	if len(r.Header.Values("Content-Type")) != 1 || !cpIsJSONContentType(r.Header.Get("Content-Type")) {
		return nil, nil, cpErrUnsupportedMedia
	}
	r.Body = http.MaxBytesReader(w, r.Body, orchestratorMaxBody)
	dec := json.NewDecoder(r.Body)
	start, err := dec.Token()
	if err != nil || start != json.Delim('{') {
		return nil, nil, cpBodyFault(err)
	}
	raw := make(map[string]json.RawMessage)
	fields := make(map[string]bool)
	for dec.More() {
		nameToken, err := dec.Token()
		if err != nil {
			return nil, nil, cpBodyFault(err)
		}
		name, ok := nameToken.(string)
		if !ok || fields[name] || !orchestratorFields[name] {
			return nil, nil, cpErrMalformedBody
		}
		fields[name] = true
		var value json.RawMessage
		if err := dec.Decode(&value); err != nil {
			return nil, nil, cpBodyFault(err)
		}
		raw[name] = value
	}
	end, err := dec.Token()
	if err != nil || end != json.Delim('}') {
		return nil, nil, cpBodyFault(err)
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, nil, cpBodyFault(err)
	}
	encoded, err := json.Marshal(raw)
	if err != nil {
		return nil, nil, cpErrMalformedBody
	}
	var req orchestratorRequest
	if err := json.Unmarshal(encoded, &req); err != nil {
		return nil, nil, cpErrMalformedBody
	}
	return &req, fields, nil
}

func validateOrchestratorRequest(req *orchestratorRequest, fields map[string]bool) error {
	if req == nil || req.SchemaVersion != cpSchemaVersion || !cpRunIDRe.MatchString(req.RunID) {
		return cpErrInvalidRequest
	}
	for _, required := range []string{"schemaVersion", "action", "runId"} {
		if !fields[required] {
			return cpErrInvalidRequest
		}
	}

	switch req.Action {
	case "advance_source":
		if !fields["sourceId"] || !fields["state"] || fields["failureCode"] ||
			req.SourceID == nil || req.State == nil {
			return cpErrInvalidRequest
		}
		step, ok := cpAdvanceSteps[*req.State]
		if !ok {
			return cpErrInvalidRequest
		}
		needsEvidence := step.EvidenceKind != ""
		if fields["artifactId"] != needsEvidence || fields["digest"] != needsEvidence ||
			(req.ArtifactID != nil) != needsEvidence || (req.Digest != nil) != needsEvidence {
			return cpErrInvalidRequest
		}
		hasSecondary := fields["secondaryArtifactId"] || fields["secondaryDigest"] ||
			req.SecondaryArtifactID != nil || req.SecondaryDigest != nil
		if hasSecondary && (step.SecondaryEvidenceKind == "" || !fields["secondaryArtifactId"] || !fields["secondaryDigest"] ||
			req.SecondaryArtifactID == nil || req.SecondaryDigest == nil) {
			return cpErrInvalidRequest
		}
		for _, counter := range []struct {
			name  string
			value *int64
		}{
			{"recordsRead", req.RecordsRead},
			{"recordsWritten", req.RecordsWritten},
			{"recordsRejected", req.RecordsRejected},
		} {
			if fields[counter.name] && counter.value == nil {
				return cpErrInvalidRequest
			}
		}
	case "attach_source_plan":
		if len(fields) != 6 || !fields["sourceId"] || !fields["artifactId"] || !fields["digest"] ||
			req.SourceID == nil || req.ArtifactID == nil || req.Digest == nil {
			return cpErrInvalidRequest
		}
	case "enter_awaiting_approval":
		if len(fields) != 3 {
			return cpErrInvalidRequest
		}
	case "fail_source":
		if len(fields) != 5 || !fields["sourceId"] || !fields["failureCode"] ||
			req.SourceID == nil || req.FailureCode == nil {
			return cpErrInvalidRequest
		}
	default:
		return cpErrInvalidRequest
	}
	return nil
}

func (h *orchestratorBridgeHandler) apply(req *orchestratorRequest) (*ControlPlaneRun, error) {
	switch req.Action {
	case "advance_source":
		upd := ControlPlaneSourceUpdate{
			RecordsRead:     req.RecordsRead,
			RecordsWritten:  req.RecordsWritten,
			RecordsRejected: req.RecordsRejected,
		}
		if req.ArtifactID != nil {
			upd.ArtifactID = *req.ArtifactID
			upd.Digest = *req.Digest
		}
		if req.SecondaryArtifactID != nil {
			upd.SecondaryArtifactID = *req.SecondaryArtifactID
			upd.SecondaryDigest = *req.SecondaryDigest
		}
		return h.target.AdvanceSource(req.RunID, *req.SourceID, *req.State, upd)
	case "attach_source_plan":
		return h.target.AttachSourcePlan(req.RunID, *req.SourceID, *req.ArtifactID, *req.Digest)
	case "enter_awaiting_approval":
		return h.target.EnterAwaitingApproval(req.RunID)
	case "fail_source":
		return h.target.FailSource(req.RunID, *req.SourceID, *req.FailureCode)
	default:
		return nil, cpErrInvalidRequest
	}
}
