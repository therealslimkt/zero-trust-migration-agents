package main

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestWebRunArtifactStoreReadsBoundedExactPaths(t *testing.T) {
	root := t.TempDir()
	runID := "mig_recordedDemo001"
	artifactID := "art_source-manifest-01"
	if err := os.MkdirAll(filepath.Join(root, runID, "artifacts"), 0o700); err != nil {
		t.Fatal(err)
	}
	body := []byte("exact synthetic evidence")
	if err := os.WriteFile(filepath.Join(root, runID, "artifacts", artifactID), body, 0o600); err != nil {
		t.Fatal(err)
	}
	store, err := OpenWebRunArtifactStore(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	got, err := store.ReadPublicationArtifact(context.Background(), runID, artifactID)
	if err != nil || string(got) != string(body) {
		t.Fatalf("artifact = %q, %v", got, err)
	}
	for _, input := range [][2]string{{"../mig_recordedDemo001", artifactID}, {runID, "../state.json"}, {runID, "bad"}} {
		if _, err := store.ReadPublicationArtifact(context.Background(), input[0], input[1]); !errors.Is(err, os.ErrNotExist) {
			t.Fatalf("unsafe path %q/%q returned %v", input[0], input[1], err)
		}
	}
}

func TestWebRunArtifactStoreRejectsEscapingSymlink(t *testing.T) {
	root := t.TempDir()
	runID := "mig_recordedDemo001"
	artifactID := "art_source-manifest-01"
	outside := filepath.Join(t.TempDir(), "private")
	if err := os.WriteFile(outside, []byte("must not escape"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, runID, "artifacts"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(root, runID, "artifacts", artifactID)); err != nil {
		t.Fatal(err)
	}
	store, err := OpenWebRunArtifactStore(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	if _, err := store.ReadPublicationArtifact(context.Background(), runID, artifactID); err == nil {
		t.Fatal("artifact root followed an escaping symlink")
	}
}

func TestWebRunArtifactStoreReadsStrictSourceDetail(t *testing.T) {
	root := t.TempDir()
	manifest := webTestManifest(t)
	detail := manifest.Sources[0]
	runID := manifest.SourceRunID
	directory := filepath.Join(root, runID, "sources")
	if err := os.MkdirAll(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	body, err := json.Marshal(detail)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "jde.json")
	if err := os.WriteFile(path, body, 0o600); err != nil {
		t.Fatal(err)
	}
	store, err := OpenWebRunArtifactStore(root)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	got, err := store.ReadLiveSourceDetail(context.Background(), runID, "jde")
	if err != nil || got.SourceID != "jde" || got.Hostname != "legacy-jde-db" {
		t.Fatalf("detail = %+v, %v", got, err)
	}
	if err := os.WriteFile(path, append(body[:len(body)-1], []byte(`,"unknown":true}`)...), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := store.ReadLiveSourceDetail(context.Background(), runID, "jde"); err == nil {
		t.Fatal("unknown source-detail field was accepted")
	}
}

func TestWebLiveDetailMustBindToControlPlaneEvidence(t *testing.T) {
	manifest := webTestManifest(t)
	detail := manifest.Sources[0]
	events := []*ControlPlaneEvent{{
		SourceID: "jde",
		EvidenceReferences: []ControlPlaneEvidence{
			{ArtifactID: detail.Compiler.LocalGemmaEvidence.ArtifactID, Kind: string(detail.Compiler.LocalGemmaEvidence.Kind), Digest: detail.Compiler.LocalGemmaEvidence.Digest},
			{ArtifactID: detail.Compiler.GeminiVertexEvidence.ArtifactID, Kind: string(detail.Compiler.GeminiVertexEvidence.Kind), Digest: detail.Compiler.GeminiVertexEvidence.Digest},
			{ArtifactID: detail.Destination.Reconciliation.Evidence.ArtifactID, Kind: string(detail.Destination.Reconciliation.Evidence.Kind), Digest: detail.Destination.Reconciliation.Evidence.Digest},
			{ArtifactID: detail.Destination.DataflowEvidence.ArtifactID, Kind: string(detail.Destination.DataflowEvidence.Kind), Digest: detail.Destination.DataflowEvidence.Digest},
			{ArtifactID: detail.Destination.BigQueryEvidence.ArtifactID, Kind: string(detail.Destination.BigQueryEvidence.Kind), Digest: detail.Destination.BigQueryEvidence.Digest},
			{ArtifactID: detail.Compiler.Actions[0].EvidenceReferences[0].ArtifactID, Kind: string(detail.Compiler.Actions[0].EvidenceReferences[0].Kind), Digest: detail.Compiler.Actions[0].EvidenceReferences[0].Digest},
		},
	}}
	// Add the remaining action references without duplicating fixture setup.
	for _, reference := range detail.Compiler.Actions[0].EvidenceReferences[1:] {
		events[0].EvidenceReferences = append(events[0].EvidenceReferences, ControlPlaneEvidence{ArtifactID: reference.ArtifactID, Kind: string(reference.Kind), Digest: reference.Digest})
	}
	source := ControlPlaneSource{SourceID: "jde", Hostname: "legacy-jde-db"}
	if !webLiveDetailMatchesControlPlane(detail, source, events) {
		t.Fatal("exact detail was rejected")
	}
	detail.Destination.BigQueryEvidence.Digest = webTestDigest("f")
	if webLiveDetailMatchesControlPlane(detail, source, events) {
		t.Fatal("detail with unbound evidence was accepted")
	}
}
