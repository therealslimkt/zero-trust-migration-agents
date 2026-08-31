package main

import (
	"errors"
	"net/http"
	"os"
)

// WebWorkflowEvidenceEntry deliberately mirrors only the browser's closed
// persisted-evidence projection. It carries no prompts, raw rows, secrets, or
// free-form reasoning. The sealed fields are validated before serialization.
type WebWorkflowEvidenceEntry struct {
	Sequence                   int64  `json:"sequence"`
	EventID                    string `json:"eventId"`
	Persisted                  bool   `json:"persisted"`
	State                      string `json:"state"`
	CheckpointRef              string `json:"checkpointRef,omitempty"`
	EvidenceDigest             string `json:"evidenceDigest"`
	Kind                       string `json:"kind"`
	WorkClass                  string `json:"workClass,omitempty"`
	ModelCall                  *bool  `json:"modelCall,omitempty"`
	NodePath                   string `json:"nodePath,omitempty"`
	AgentID                    string `json:"agentId,omitempty"`
	DeterministicComponentID   string `json:"deterministicComponentId,omitempty"`
	ApprovalKind               string `json:"approvalKind,omitempty"`
	InterruptID                string `json:"interruptId,omitempty"`
	ResumeChannel              string `json:"resumeChannel,omitempty"`
	SubjectDigest              string `json:"subjectDigest,omitempty"`
	Decision                   string `json:"decision,omitempty"`
	ApprovalID                 string `json:"approvalId,omitempty"`
}

type WebWorkflowEvidenceProjection struct {
	Status       string                     `json:"status"`
	ReplayCursor string                     `json:"replayCursor"`
	Complete     bool                       `json:"complete"`
	Entries      []WebWorkflowEvidenceEntry `json:"entries"`
}

func webKnownWorkflowEvidenceState(state string) bool {
	switch state {
	case "queued", "running", "interrupted", "succeeded", "failed", "cancelled":
		return true
	default:
		return false
	}
}

func webValidWorkflowEvidence(projection WebWorkflowEvidenceProjection) bool {
	if projection.Status != "ready" || !webSafeBoundedText(projection.ReplayCursor, 256) || len(projection.Entries) == 0 || len(projection.Entries) > 500 {
		return false
	}
	seen := make(map[string]struct{}, len(projection.Entries))
	for index, entry := range projection.Entries {
		if entry.Sequence != int64(index+1) || !webSafeBoundedText(entry.EventID, 256) || !entry.Persisted ||
			!webKnownWorkflowEvidenceState(entry.State) || !cpDigestRe.MatchString(entry.EvidenceDigest) ||
			(entry.CheckpointRef != "" && !webSafeBoundedText(entry.CheckpointRef, 256)) {
			return false
		}
		if _, exists := seen[entry.EventID]; exists { return false }
		seen[entry.EventID] = struct{}{}
		switch entry.Kind {
		case "node":
			if !webSafeBoundedText(entry.NodePath, 256) || entry.ModelCall == nil { return false }
			if *entry.ModelCall {
				if entry.WorkClass != "model_call" || !webSafeBoundedText(entry.AgentID, 256) || entry.DeterministicComponentID != "" { return false }
			} else if (entry.WorkClass != "deterministic_function" && entry.WorkClass != "control_flow") || !webSafeBoundedText(entry.DeterministicComponentID, 256) || entry.AgentID != "" { return false }
		case "approval_interrupt":
			if (entry.ApprovalKind != "simulation_approval" && entry.ApprovalKind != "production_approval") || !webSafeBoundedText(entry.InterruptID, 256) || entry.ResumeChannel != "approval_endpoint" || !cpDigestRe.MatchString(entry.SubjectDigest) || (entry.Decision != "pending" && entry.Decision != "approved" && entry.Decision != "rejected") { return false }
			if (entry.Decision == "pending" && entry.ApprovalID != "") || (entry.Decision != "pending" && !cpApprovalIDRe.MatchString(entry.ApprovalID)) { return false }
		default:
			return false
		}
	}
	return true
}

func (h *webBFFHandler) handleWorkflowEvidence(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) { return }
	identity, ok := h.authenticate(w, r)
	if !ok { return }
	runID := r.PathValue("run_id")
	if _, _, _, owned := h.ownedRun(w, identity.Subject, runID); !owned { return }
	if h.workflowEvidence == nil { webWriteProblem(w, cpErrNotFound); return }
	projection, err := h.workflowEvidence.ReadPersistedWorkflowEvidence(r.Context(), runID)
	if errors.Is(err, os.ErrNotExist) { webWriteProblem(w, cpErrNotFound); return }
	if err != nil || !webValidWorkflowEvidence(projection) { webWriteProblem(w, cpErrInternal); return }
	webWriteJSON(w, http.StatusOK, projection)
}
