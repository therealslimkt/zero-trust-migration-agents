package main

// This file derives public-demo eligibility from durable control-plane facts.
// The manifest is untrusted presentation input: it may enrich a replay with
// synthetic samples, but it cannot establish ownership, classification,
// approval, completion, reconciliation, or evidence provenance.

func (h *webBFFHandler) derivePublicationTrust(ownerUID string, manifest DemoManifest) (WebTrustedRunPublicationRecord, error) {
	rejected := func() (WebTrustedRunPublicationRecord, error) {
		return WebTrustedRunPublicationRecord{}, webErrPublicationRejected
	}
	if _, ok := h.syntheticRuns[manifest.SourceRunID]; !ok {
		return WebTrustedRunPublicationRecord{}, cpErrNotFound
	}
	ownership, ok := h.store.RunOwnership(manifest.SourceRunID)
	if !ok || ownership.OwnerUID != ownerUID {
		return WebTrustedRunPublicationRecord{}, cpErrNotFound
	}
	run, events, err := h.runs.WebRunSnapshot(manifest.SourceRunID)
	if err != nil || run == nil {
		return WebTrustedRunPublicationRecord{}, cpErrNotFound
	}
	approval, err := h.runs.Approval(manifest.SourceRunID)
	if err != nil || approval == nil {
		return rejected()
	}
	actor, ok := webActorForUID(ownerUID)
	if !ok || approval.DecidedBy != actor || approval.Decision != "approve" ||
		approval.ResultingState != ControlPlaneStateApproved || approval.PlanDigest != run.PortfolioPlanDigest {
		return rejected()
	}
	if run.State != ControlPlaneStateCompleted || run.PortfolioPlanDigest == "" ||
		manifest.PortfolioPlanDigest != run.PortfolioPlanDigest || len(run.Sources) != len(webCanonicalSourceHostnames) {
		return rejected()
	}

	manifestSources := make(map[WebSourceID]WebSourceReplay, len(manifest.Sources))
	for _, source := range manifest.Sources {
		if _, duplicate := manifestSources[source.SourceID]; duplicate {
			return rejected()
		}
		manifestSources[source.SourceID] = source
	}
	var totalRead, totalWritten, totalRejected int64
	for _, source := range run.Sources {
		manifestSource, exists := manifestSources[WebSourceID(source.SourceID)]
		if !exists || source.State != ControlPlaneStateCompleted || manifestSource.Hostname != source.Hostname ||
			source.RecordsRead < 0 || source.RecordsWritten < 0 || source.RecordsRejected < 0 ||
			source.RecordsRead != source.RecordsWritten+source.RecordsRejected ||
			manifestSource.Destination.Reconciliation.RecordsRead != source.RecordsRead ||
			manifestSource.Destination.Reconciliation.RecordsWritten != source.RecordsWritten ||
			manifestSource.Destination.Reconciliation.RecordsRejected != source.RecordsRejected ||
			manifestSource.Destination.Reconciliation.OutputRows != source.RecordsWritten ||
			manifestSource.Compiler.Approval.ApprovalID != approval.ApprovalID ||
			manifestSource.Compiler.Approval.Decision != "approved" ||
			manifestSource.Compiler.Approval.DecidedAt != approval.DecidedAt ||
			manifestSource.Compiler.Approval.PlanDigest != approval.PlanDigest {
			return rejected()
		}
		totalRead += source.RecordsRead
		totalWritten += source.RecordsWritten
		totalRejected += source.RecordsRejected
	}
	if len(manifestSources) != len(run.Sources) ||
		manifest.Reconciliation.RecordsRead != totalRead ||
		manifest.Reconciliation.RecordsWritten != totalWritten ||
		manifest.Reconciliation.RecordsRejected != totalRejected ||
		manifest.Reconciliation.OutputRows != totalWritten {
		return rejected()
	}

	if len(manifest.Events) != len(events) {
		return rejected()
	}
	catalog := make(map[ControlPlaneEvidence]struct{}, len(manifest.Evidence))
	for _, reference := range manifest.Evidence {
		catalog[ControlPlaneEvidence{ArtifactID: reference.ArtifactID, Kind: string(reference.Kind), Digest: reference.Digest}] = struct{}{}
	}
	verificationSeen := make(map[string]bool, len(run.Sources))
	for index, event := range events {
		manifestEvent := manifest.Events[index]
		if manifestEvent.Sequence != int64(index+1) || manifestEvent.EventID != event.EventID ||
			manifestEvent.Timestamp != event.Timestamp || string(manifestEvent.SourceID) != event.SourceID ||
			manifestEvent.EventType != event.EventType || manifestEvent.State != WebRunState(event.State) ||
			manifestEvent.Summary != event.Summary || len(manifestEvent.EvidenceReferences) != len(event.EvidenceReferences) {
			return rejected()
		}
		for evidenceIndex, reference := range event.EvidenceReferences {
			manifestReference := manifestEvent.EvidenceReferences[evidenceIndex]
			if manifestReference.ArtifactID != reference.ArtifactID || string(manifestReference.Kind) != reference.Kind ||
				manifestReference.Digest != reference.Digest {
				return rejected()
			}
			if _, exists := catalog[reference]; !exists {
				return rejected()
			}
		}
		if event.EventType == "source.verification.completed" {
			kinds := make(map[string]bool)
			for _, reference := range event.EvidenceReferences {
				kinds[reference.Kind] = true
			}
			if !kinds["reconciliation"] || !kinds["audit_log"] {
				return rejected()
			}
			verificationSeen[event.SourceID] = true
		}
	}
	for _, source := range run.Sources {
		if !verificationSeen[source.SourceID] {
			return rejected()
		}
	}

	return WebTrustedRunPublicationRecord{
		SourceRunID:           run.RunID,
		DataClass:             DataClassSyntheticDemo,
		State:                 WebRunState(run.State),
		FullyReconciled:       true,
		OwnerApprovalVerified: true,
		PortfolioPlanDigest:   run.PortfolioPlanDigest,
	}, nil
}
