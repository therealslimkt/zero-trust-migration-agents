package main

import "errors"

// authorizeSyntheticPublication derives every publication gate from durable
// control-plane and ownership state. It is intentionally not an HTTP handler:
// explicit operator/admin wiring may invoke it after selecting the one demo
// run, but browser input can never assert classification or reconciliation.
func (h *webBFFHandler) authorizeSyntheticPublication(ownerUID, runID string) error {
	ownership, ok := h.store.RunOwnership(runID)
	if !ok || ownership.OwnerUID != ownerUID {
		return cpErrNotFound
	}
	run, events, err := h.runs.WebRunSnapshot(runID)
	if err != nil {
		return cpErrNotFound
	}
	approval, err := h.runs.Approval(runID)
	if err != nil {
		return cpErrNotFound
	}
	if run.State != ControlPlaneStateCompleted || !validWebDigest(run.PortfolioPlanDigest) ||
		approval.Decision != "approve" || approval.PlanDigest != run.PortfolioPlanDigest {
		return errors.New("web publication eligibility: run is not completed under its approved plan")
	}
	if len(run.Sources) != len(cpCanonicalSources) {
		return errors.New("web publication eligibility: incomplete source portfolio")
	}
	reconciled := make(map[string]bool, len(run.Sources))
	for _, event := range events {
		if event.EventType != "source.verification.completed" || event.SourceID == "" {
			continue
		}
		hasReconciliation, hasAudit := false, false
		for _, evidence := range event.EvidenceReferences {
			if evidence.Kind == "reconciliation" {
				hasReconciliation = true
			}
			if evidence.Kind == "audit_log" {
				hasAudit = true
			}
		}
		reconciled[event.SourceID] = hasReconciliation && hasAudit
	}
	for _, source := range run.Sources {
		if source.State != ControlPlaneStateCompleted || !reconciled[source.SourceID] {
			return errors.New("web publication eligibility: source reconciliation is incomplete")
		}
	}
	return h.store.putTrustedPublicationRecord(ownerUID, WebTrustedRunPublicationRecord{SourceRunID: run.RunID, DataClass: DataClassSyntheticDemo, State: WebRunState(ControlPlaneStateCompleted), FullyReconciled: true, OwnerApprovalVerified: true, PortfolioPlanDigest: run.PortfolioPlanDigest})
}
