package main

import (
	"errors"
	"testing"
)

type webPublicationTrustRuns struct {
	run      *ControlPlaneRun
	events   []*ControlPlaneEvent
	approval *ControlPlaneApproval
}

func (f webPublicationTrustRuns) CreateRunWithOwnership(*cpCreateRequest, func(*ControlPlaneRun) error) (*ControlPlaneRun, error) {
	return nil, errors.New("unused")
}

func (f webPublicationTrustRuns) WebRunSnapshot(string) (*ControlPlaneRun, []*ControlPlaneEvent, error) {
	return f.run, f.events, nil
}

func (f webPublicationTrustRuns) Approval(string) (*ControlPlaneApproval, error) {
	return f.approval, nil
}

func (f webPublicationTrustRuns) Decide(string, *cpApprovalRequest) (*ControlPlaneApproval, error) {
	return nil, errors.New("unused")
}

func webTrustFixture(t *testing.T) (DemoManifest, string, webPublicationTrustRuns) {
	t.Helper()
	manifest := webTestManifest(t)
	verificationEvents := make([]WebReplayEvent, 0, 3)
	for index, source := range manifest.Sources {
		verificationEvents = append(verificationEvents, WebReplayEvent{
			Sequence:  int64(4 + index),
			EventID:   []string{"evt_jdeverified00001", "evt_maxverified0001", "evt_btrverified0001"}[index],
			Timestamp: "2026-08-27T08:04:00Z",
			SourceID:  source.SourceID,
			EventType: "source.verification.completed",
			State:     "completed",
			Summary:   "Synthetic source verification completed.",
			EvidenceReferences: []WebEvidenceReference{
				source.Destination.Reconciliation.Evidence,
				manifest.Evidence[6],
			},
		})
	}
	completion := manifest.Events[len(manifest.Events)-1]
	completion.Sequence = 7
	manifest.Events = append(manifest.Events[:3], verificationEvents...)
	manifest.Events = append(manifest.Events, completion)
	digest, err := DemoManifestDigest(manifest)
	if err != nil {
		t.Fatal(err)
	}
	manifest.BundleDigest = digest

	ownerUID := "firebase-owner-001"
	actor, ok := webActorForUID(ownerUID)
	if !ok {
		t.Fatal("fixture owner should produce a durable actor")
	}
	run := &ControlPlaneRun{
		RunID: manifest.SourceRunID, State: ControlPlaneStateCompleted,
		PortfolioPlanDigest: manifest.PortfolioPlanDigest,
	}
	for _, source := range manifest.Sources {
		reconciliation := source.Destination.Reconciliation
		run.Sources = append(run.Sources, ControlPlaneSource{
			SourceID: string(source.SourceID), Hostname: source.Hostname,
			State: ControlPlaneStateCompleted, RecordsRead: reconciliation.RecordsRead,
			RecordsWritten: reconciliation.RecordsWritten, RecordsRejected: reconciliation.RecordsRejected,
		})
	}
	events := make([]*ControlPlaneEvent, 0, len(manifest.Events))
	for _, event := range manifest.Events {
		refs := make([]ControlPlaneEvidence, 0, len(event.EvidenceReferences))
		for _, reference := range event.EvidenceReferences {
			refs = append(refs, ControlPlaneEvidence{ArtifactID: reference.ArtifactID, Kind: string(reference.Kind), Digest: reference.Digest})
		}
		events = append(events, &ControlPlaneEvent{
			EventID: event.EventID, RunID: manifest.SourceRunID, SourceID: string(event.SourceID),
			EventType: event.EventType, Timestamp: event.Timestamp, Summary: event.Summary,
			EvidenceReferences: refs, State: ControlPlaneState(event.State),
		})
	}
	approval := &ControlPlaneApproval{
		ApprovalID: manifest.Sources[0].Compiler.Approval.ApprovalID,
		RunID:      manifest.SourceRunID, PlanDigest: manifest.PortfolioPlanDigest,
		Decision: "approve", ResultingState: ControlPlaneStateApproved,
		DecidedBy: actor, DecidedAt: manifest.Sources[0].Compiler.Approval.DecidedAt,
	}
	return manifest, ownerUID, webPublicationTrustRuns{run: run, events: events, approval: approval}
}

func TestDerivePublicationTrustFromDurableFacts(t *testing.T) {
	manifest, ownerUID, runs := webTrustFixture(t)
	store, err := OpenWebStateStore(t.TempDir() + "/state.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.PutRunOwnership(WebRunOwnershipRecord{
		RunID: manifest.SourceRunID, OwnerUID: ownerUID, PortfolioName: "Synthetic demo",
		Owner:     WebIdentitySummary{Subject: ownerUID, DisplayName: "Demo Owner", Email: "owner@example.test"},
		CreatedAt: "2026-08-27T08:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}
	h := &webBFFHandler{runs: runs, store: store, syntheticRuns: map[string]struct{}{manifest.SourceRunID: {}}}

	trusted, err := h.derivePublicationTrust(ownerUID, manifest)
	if err != nil {
		t.Fatalf("derive trust: %v", err)
	}
	if trusted.SourceRunID != manifest.SourceRunID || trusted.DataClass != DataClassSyntheticDemo ||
		trusted.State != "completed" || !trusted.FullyReconciled || !trusted.OwnerApprovalVerified ||
		trusted.PortfolioPlanDigest != manifest.PortfolioPlanDigest {
		t.Fatalf("unexpected trusted record: %+v", trusted)
	}
}

func TestDerivePublicationTrustFailsClosed(t *testing.T) {
	manifest, ownerUID, runs := webTrustFixture(t)
	store, err := OpenWebStateStore(t.TempDir() + "/state.json")
	if err != nil {
		t.Fatal(err)
	}
	if err := store.PutRunOwnership(WebRunOwnershipRecord{
		RunID: manifest.SourceRunID, OwnerUID: ownerUID, PortfolioName: "Synthetic demo",
		Owner:     WebIdentitySummary{Subject: ownerUID, DisplayName: "Demo Owner", Email: "owner@example.test"},
		CreatedAt: "2026-08-27T08:00:00Z",
	}); err != nil {
		t.Fatal(err)
	}

	tests := []struct {
		name      string
		owner     string
		allowlist bool
		mutate    func(*DemoManifest, *webPublicationTrustRuns)
	}{
		{name: "not deployment classified", owner: ownerUID},
		{name: "foreign owner", owner: "firebase-owner-002", allowlist: true},
		{name: "approval actor mismatch", owner: ownerUID, allowlist: true, mutate: func(_ *DemoManifest, runs *webPublicationTrustRuns) {
			runs.approval.DecidedBy = "web_00000000000000000000000000000000"
		}},
		{name: "counter mismatch", owner: ownerUID, allowlist: true, mutate: func(manifest *DemoManifest, _ *webPublicationTrustRuns) {
			manifest.Sources[0].Destination.Reconciliation.RecordsWritten++
		}},
		{name: "event mismatch", owner: ownerUID, allowlist: true, mutate: func(manifest *DemoManifest, _ *webPublicationTrustRuns) {
			manifest.Events[0].Summary = "Browser supplied a different event."
		}},
		{name: "verification evidence absent", owner: ownerUID, allowlist: true, mutate: func(_ *DemoManifest, runs *webPublicationTrustRuns) {
			runs.events[3].EvidenceReferences = runs.events[3].EvidenceReferences[:1]
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			candidate := cloneWebTestManifest(t, manifest)
			candidate.BundleDigest = manifest.BundleDigest
			fixtureRuns := webPublicationTrustRuns{run: runs.run.clone(), approval: func() *ControlPlaneApproval { copy := *runs.approval; return &copy }()}
			for _, event := range runs.events {
				fixtureRuns.events = append(fixtureRuns.events, event.clone())
			}
			if test.mutate != nil {
				test.mutate(&candidate, &fixtureRuns)
			}
			allowlist := map[string]struct{}{}
			if test.allowlist {
				allowlist[manifest.SourceRunID] = struct{}{}
			}
			h := &webBFFHandler{runs: fixtureRuns, store: store, syntheticRuns: allowlist}
			if _, err := h.derivePublicationTrust(test.owner, candidate); err == nil {
				t.Fatal("untrusted publication was accepted")
			}
		})
	}
}
