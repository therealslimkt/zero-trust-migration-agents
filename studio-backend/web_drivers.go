package main

import (
	"context"
	"net/http"
	"time"
)

func (h *webBFFHandler) handleDriverResearchCreate(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) || !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	if h.researcher == nil {
		webWriteProblem(w, webErrResearchUnavailable)
		return
	}
	var req WebDriverResearchRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if !webValidResearchRequest(req) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	var verifiedSetup *WebCloudSetupRecord
	for _, setup := range h.store.CloudSetupsForOwner(identity.Subject) {
		if setup.Status == webCloudSetupVerified && setup.ProjectID == req.ProjectID {
			candidate := setup
			verifiedSetup = &candidate
		}
	}
	if verifiedSetup == nil {
		webWriteProblem(w, webErrCloudSetupNotVerified)
		return
	}
	idPart, err := webRandomHex(12)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	now := h.now().UTC()
	researchID := "research_" + idPart
	record := WebDriverResearchRecord{ResearchID: researchID, OwnerUID: identity.Subject, Status: webResearchQueued, Request: req, CreatedAt: h.stamp(now), UpdatedAt: h.stamp(now)}
	if err := h.store.CreateDriverResearch(record); err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	accepted := h.runAsync(func() {
		started := h.stamp(h.now())
		if err := h.store.SetDriverResearchRunning(researchID, started); err != nil {
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
		defer cancel()
		finding, err := h.researcher.ResearchDrivers(ctx, req)
		if err != nil {
			_ = h.store.FailDriverResearch(researchID, "DRIVER_RESEARCH_FAILED", h.stamp(h.now()))
			return
		}
		result := WebDriverResearchResponse{SchemaVersion: WebSchemaVersion, ResearchID: researchID, Model: finding.Model, ProjectID: req.ProjectID, CreatedAt: record.CreatedAt, Candidates: append([]WebDriverCandidate(nil), finding.Candidates...), EvidenceDigest: finding.EvidenceDigest}
		if !webValidResearchResult(result, researchID) {
			_ = h.store.FailDriverResearch(researchID, "DRIVER_RESEARCH_INVALID", h.stamp(h.now()))
			return
		}
		_ = h.store.CompleteDriverResearch(researchID, result, h.stamp(h.now()))
	})
	if !accepted {
		_ = h.store.FailDriverResearch(researchID, "DRIVER_RESEARCH_CAPACITY", h.stamp(h.now()))
		webWriteProblem(w, webErrResearchUnavailable)
		return
	}
	w.Header().Set("Location", "/api/web/v1/drivers/research/"+researchID)
	webWriteJSON(w, http.StatusAccepted, WebDriverResearchAccepted{SchemaVersion: WebSchemaVersion, ResearchID: researchID, Status: webResearchQueued, StatusLocation: "/api/web/v1/drivers/research/" + researchID, CreatedAt: record.CreatedAt})
}

func (h *webBFFHandler) handleDriverResearchStatus(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	researchID := r.PathValue("research_id")
	if !webResearchIDPattern.MatchString(researchID) {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	record, found := h.store.DriverResearch(identity.Subject, researchID)
	if !found {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	webWriteJSON(w, http.StatusOK, WebDriverResearchStatusResponse{SchemaVersion: WebSchemaVersion, ResearchID: record.ResearchID, Status: record.Status, UpdatedAt: record.UpdatedAt, Result: record.Result, FailureCode: record.FailureCode})
}

func (h *webBFFHandler) handleDriverApproval(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) || !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	researchID := r.PathValue("research_id")
	if !webResearchIDPattern.MatchString(researchID) {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	var req WebDriverApprovalRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion || req.ResearchID != researchID || !webCandidateIDPattern.MatchString(req.CandidateID) || !validWebDigest(req.EvidenceDigest) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	record, found := h.store.DriverResearch(identity.Subject, researchID)
	if !found {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	if record.Status != webResearchCompleted || record.Result == nil {
		webWriteProblem(w, webErrResearchNotCompleted)
		return
	}
	if record.Approval != nil {
		webWriteProblem(w, webErrDriverAlreadyApproved)
		return
	}
	if record.Result.EvidenceDigest != req.EvidenceDigest {
		webWriteProblem(w, webErrStaleEvidenceDigest)
		return
	}
	var candidate *WebDriverCandidate
	for index := range record.Result.Candidates {
		if record.Result.Candidates[index].CandidateID == req.CandidateID {
			candidate = &record.Result.Candidates[index]
			break
		}
	}
	if candidate == nil {
		webWriteProblem(w, webErrUnknownDriverCandidate)
		return
	}
	approval := WebDriverApprovalResponse{SchemaVersion: WebSchemaVersion, ResearchID: researchID, CandidateID: candidate.CandidateID, ApprovedAt: h.stamp(h.now())}
	if candidate.Redistribution != "allowed" {
		approval.Status = "pending_upload"
		approval.RetrievalMode = "manual_vendor_upload"
	} else {
		if h.driverRegistry == nil {
			webWriteProblem(w, webErrResearchUnavailable)
			return
		}
		var verifiedSetup *WebCloudSetupRecord
		for _, setup := range h.store.CloudSetupsForOwner(identity.Subject) {
			if setup.Status == webCloudSetupVerified && setup.ProjectID == record.Request.ProjectID {
				candidateSetup := setup
				verifiedSetup = &candidateSetup
			}
		}
		if verifiedSetup == nil {
			webWriteProblem(w, webErrCloudSetupNotVerified)
			return
		}
		fingerprint, err := h.driverRegistry.FingerprintArtifactRegistryRemote(r.Context(), *verifiedSetup, *candidate)
		if err != nil || !validWebDigest(fingerprint) {
			webWriteProblem(w, cpErrInternal)
			return
		}
		approval.Status = "verified"
		approval.RetrievalMode = "artifact_registry_remote"
		approval.ArtifactFingerprint = fingerprint
	}
	if err := h.store.PutDriverApproval(researchID, approval); err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	webWriteJSON(w, http.StatusOK, approval)
}
