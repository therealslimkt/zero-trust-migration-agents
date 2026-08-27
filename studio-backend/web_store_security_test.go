package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
)

func webTestStoredDemo(t *testing.T) (DemoManifest, WebStoredDemo) {
	t.Helper()
	manifest := webTestManifest(t)
	body, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	return manifest, WebStoredDemo{DemoID: manifest.DemoID, BundleDigest: manifest.BundleDigest, ManifestJSON: body}
}

func TestWebStorePublicationUsesExternalContentAddressedBodyAndSurvivesRestart(t *testing.T) {
	dir := t.TempDir()
	statePath := filepath.Join(dir, "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	manifest, candidate := webTestStoredDemo(t)
	stored, created, err := store.CreateOrGetPublishedDemo(context.Background(), candidate)
	if err != nil || !created || !bytes.Equal(stored.ManifestJSON, candidate.ManifestJSON) {
		t.Fatalf("create = (%t, %v), body equal = %t", created, err, bytes.Equal(stored.ManifestJSON, candidate.ManifestJSON))
	}

	record := store.snap.Publications[0]
	bodyPath, ok := store.publicationAbsolutePath(record)
	if !ok {
		t.Fatal("publication path was not store-derived")
	}
	info, err := os.Lstat(bodyPath)
	if err != nil {
		t.Fatal(err)
	}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		t.Fatalf("publication mode = %v", info.Mode())
	}
	snapshotBytes, err := os.ReadFile(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(snapshotBytes, candidate.ManifestJSON) || bytes.Contains(snapshotBytes, []byte(`"manifestJson"`)) {
		t.Fatal("snapshot embeds the publication body")
	}
	if !bytes.Contains(snapshotBytes, []byte(`"manifestPath"`)) || !bytes.Contains(snapshotBytes, []byte(`"manifestSha256"`)) {
		t.Fatal("snapshot is missing publication body metadata")
	}

	// An ordinary metadata mutation must leave the immutable bundle untouched.
	bodyBefore, err := os.ReadFile(bodyPath)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.PutRunOwnership(webTestOwnershipRecord(1, "another-owner")); err != nil {
		t.Fatal(err)
	}
	bodyAfter, err := os.ReadFile(bodyPath)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(bodyBefore, bodyAfter) {
		t.Fatal("ordinary mutation rewrote the immutable publication body")
	}

	restarted, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatalf("restart: %v", err)
	}
	byID, ok := restarted.PublishedDemoByID(manifest.DemoID)
	if !ok || !bytes.Equal(byID.ManifestJSON, candidate.ManifestJSON) {
		t.Fatal("publication did not survive restart exactly")
	}
	byDigest, ok := restarted.PublishedDemoByDigest(manifest.BundleDigest)
	if !ok || byDigest.DemoID != manifest.DemoID {
		t.Fatal("content-addressed index did not survive restart")
	}
}

func TestWebStorePublicationTamperFailsClosedOnReadAndRestart(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	manifest, candidate := webTestStoredDemo(t)
	if _, _, err := store.CreateOrGetPublishedDemo(context.Background(), candidate); err != nil {
		t.Fatal(err)
	}
	bodyPath, ok := store.publicationAbsolutePath(store.snap.Publications[0])
	if !ok {
		t.Fatal("publication path was not store-derived")
	}
	tampered := append([]byte(nil), candidate.ManifestJSON...)
	tampered[len(tampered)-2] ^= 1
	if err := os.WriteFile(bodyPath, tampered, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, ok := store.PublishedDemoByID(manifest.DemoID); ok {
		t.Fatal("tampered publication was served by demo id")
	}
	if _, ok := store.PublishedDemoByDigest(manifest.BundleDigest); ok {
		t.Fatal("tampered publication was served by digest")
	}
	if _, err := OpenWebStateStore(statePath); err == nil {
		t.Fatal("restart accepted a tampered publication body")
	}
}

func TestWebStoreMissingPublicationBodyFailsClosedOnReadAndRestart(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	manifest, candidate := webTestStoredDemo(t)
	if _, _, err := store.CreateOrGetPublishedDemo(context.Background(), candidate); err != nil {
		t.Fatal(err)
	}
	bodyPath, ok := store.publicationAbsolutePath(store.snap.Publications[0])
	if !ok {
		t.Fatal("publication path was not store-derived")
	}
	if err := os.Remove(bodyPath); err != nil {
		t.Fatal(err)
	}
	if _, ok := store.PublishedDemoByID(manifest.DemoID); ok {
		t.Fatal("publication with a missing body was served")
	}
	if _, err := OpenWebStateStore(statePath); err == nil {
		t.Fatal("restart accepted a publication with a missing body")
	}
}

func TestWebStoreReloadRecomputesCanonicalManifestDigest(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	manifest, candidate := webTestStoredDemo(t)
	if _, _, err := store.CreateOrGetPublishedDemo(context.Background(), candidate); err != nil {
		t.Fatal(err)
	}

	// Forge a self-consistent file SHA/path and summary while retaining the old
	// canonical bundleDigest. Reload must still reject the manifest itself.
	manifest.Title = "Tampered but safe-looking title"
	forgedBody, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	forgedSHA := webBodySHA256(forgedBody)
	record := store.snap.Publications[0]
	record.Title = manifest.Title
	record.ManifestSHA256 = forgedSHA
	record.ManifestPath = store.publicationRelativePath(forgedSHA)
	forgedPath, ok := store.publicationAbsolutePath(record)
	if !ok {
		t.Fatal("forged test path was not valid")
	}
	if err := os.WriteFile(forgedPath, forgedBody, 0o600); err != nil {
		t.Fatal(err)
	}
	snapshotBytes, err := json.Marshal(store.snap)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(statePath, snapshotBytes, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := OpenWebStateStore(statePath); err == nil {
		t.Fatal("restart accepted a manifest whose canonical bundle digest was stale")
	}
}

func TestWebStorePublicationRejectsUnknownManifestFields(t *testing.T) {
	store, err := OpenWebStateStore(filepath.Join(t.TempDir(), "web-state.json"))
	if err != nil {
		t.Fatal(err)
	}
	manifest, candidate := webTestStoredDemo(t)
	var document map[string]any
	if err := json.Unmarshal(candidate.ManifestJSON, &document); err != nil {
		t.Fatal(err)
	}
	document["unexpected"] = true
	candidate.ManifestJSON, err = json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := store.CreateOrGetPublishedDemo(context.Background(), candidate); !errors.Is(err, errWebStoreInvalid) {
		t.Fatalf("unknown-field create error = %v", err)
	}
	if _, ok := store.PublishedDemoByID(manifest.DemoID); ok {
		t.Fatal("unknown-field manifest was indexed")
	}
}

func TestWebStorePublicationRejectsDuplicateJSONNames(t *testing.T) {
	store, err := OpenWebStateStore(filepath.Join(t.TempDir(), "web-state.json"))
	if err != nil {
		t.Fatal(err)
	}
	_, candidate := webTestStoredDemo(t)
	candidate.ManifestJSON = bytes.Replace(candidate.ManifestJSON,
		[]byte(`"schemaVersion":`),
		[]byte(`"schemaVersion":"`+WebSchemaVersion+`","schemaVersion":`), 1)
	if _, _, err := store.CreateOrGetPublishedDemo(context.Background(), candidate); !errors.Is(err, errWebStoreInvalid) {
		t.Fatalf("duplicate-name create error = %v", err)
	}
}

func TestWebStoreConcurrentIdenticalPublicationIsCreateOnce(t *testing.T) {
	store, err := OpenWebStateStore(filepath.Join(t.TempDir(), "web-state.json"))
	if err != nil {
		t.Fatal(err)
	}
	_, candidate := webTestStoredDemo(t)
	const workers = 24
	var wg sync.WaitGroup
	results := make(chan bool, workers)
	errs := make(chan error, workers)
	for range workers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			stored, created, err := store.CreateOrGetPublishedDemo(context.Background(), candidate)
			if err == nil && (!bytes.Equal(stored.ManifestJSON, candidate.ManifestJSON) || stored.BundleDigest != candidate.BundleDigest) {
				err = errors.New("store returned a different immutable value")
			}
			results <- created
			errs <- err
		}()
	}
	wg.Wait()
	close(results)
	close(errs)
	createdCount := 0
	for created := range results {
		if created {
			createdCount++
		}
	}
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if createdCount != 1 || len(store.snap.Publications) != 1 {
		t.Fatalf("created = %d, publication records = %d", createdCount, len(store.snap.Publications))
	}
}

func TestWebStorePostRenameSyncFailureRetainsNewAuthoritativeState(t *testing.T) {
	statePath := filepath.Join(t.TempDir(), "web-state.json")
	store, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	record := webTestOwnershipRecord(1, "owner")
	store.syncDirectory = func(string) error { return errors.New("injected directory sync failure") }
	if err := store.PutRunOwnership(record); !errors.Is(err, errWebStoreCorrupt) {
		t.Fatalf("mutation error = %v", err)
	}
	if inMemory, ok := store.RunOwnership(record.RunID); !ok || inMemory.OwnerUID != record.OwnerUID {
		t.Fatal("post-rename state was not retained in memory")
	}

	// Rename completed before the injected durability failure, so a retry or
	// restart observes the same state instead of allowing stale overwrite.
	restarted, err := OpenWebStateStore(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if onDisk, ok := restarted.RunOwnership(record.RunID); !ok || onDisk.OwnerUID != record.OwnerUID {
		t.Fatal("post-rename state on disk diverged from memory")
	}
}

func webTestOwnershipRecord(index int, owner string) WebRunOwnershipRecord {
	return WebRunOwnershipRecord{
		RunID:         fmt.Sprintf("mig_%012d", index),
		OwnerUID:      owner,
		PortfolioName: "Synthetic portfolio",
		Owner:         WebIdentitySummary{Subject: owner, DisplayName: "Owner", Email: owner + "@example.test"},
		CreatedAt:     "2026-08-27T12:00:00.000Z",
	}
}

func webTestSetupRecord(index int, owner string) WebCloudSetupRecord {
	return WebCloudSetupRecord{
		SetupID: fmt.Sprintf("setup_%08d", index), OwnerUID: owner,
		ProjectID: "owner-project1", Region: "us-central1", DatasetPrefix: "owner",
		CommandDigest: webTestDigest("a"), ReceiptSHA256: fmt.Sprintf("%064x", index+1),
		Status: webCloudSetupPending, CreatedAt: "2026-08-27T12:00:00.000Z", ExpiresAt: "2026-08-27T13:00:00.000Z",
	}
}

func webTestResearchRecord(index int, owner string) WebDriverResearchRecord {
	return WebDriverResearchRecord{
		ResearchID: fmt.Sprintf("research_%08d", index), OwnerUID: owner, Status: webResearchQueued,
		Request: WebDriverResearchRequest{
			SchemaVersion: WebSchemaVersion, ProjectID: "owner-project1", DatabaseFamily: "Btrieve",
			DatabaseVersion: "6.15", ApplicationLayer: "Sage", JavaRuntime: "17", ConnectivityMode: "tailscale",
		},
		CreatedAt: "2026-08-27T12:00:00.000Z", UpdatedAt: "2026-08-27T12:00:00.000Z",
	}
}

func TestWebStorePerOwnerCreateLimitsPreserveCapacityForOtherOwners(t *testing.T) {
	tests := []struct {
		name     string
		populate func(*webSnapshot)
		create   func(*WebStateStore, string) error
	}{
		{
			name: "ownerships",
			populate: func(snap *webSnapshot) {
				for i := 0; i < webMaxOwnerOwnerships; i++ {
					record := webTestOwnershipRecord(i, "owner")
					snap.RunOwnerships = append(snap.RunOwnerships, &record)
				}
			},
			create: func(store *WebStateStore, owner string) error {
				return store.PutRunOwnership(webTestOwnershipRecord(999, owner))
			},
		},
		{
			name: "setups",
			populate: func(snap *webSnapshot) {
				for i := 0; i < webMaxOwnerSetups; i++ {
					record := webTestSetupRecord(i, "owner")
					snap.CloudSetups = append(snap.CloudSetups, &record)
				}
			},
			create: func(store *WebStateStore, owner string) error {
				return store.PutCloudSetup(webTestSetupRecord(999, owner))
			},
		},
		{
			name: "research",
			populate: func(snap *webSnapshot) {
				for i := 0; i < webMaxOwnerResearch; i++ {
					record := webTestResearchRecord(i, "owner")
					snap.DriverResearch = append(snap.DriverResearch, &record)
				}
			},
			create: func(store *WebStateStore, owner string) error {
				return store.CreateDriverResearch(webTestResearchRecord(999, owner))
			},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			store, err := OpenWebStateStore(filepath.Join(t.TempDir(), "web-state.json"))
			if err != nil {
				t.Fatal(err)
			}
			test.populate(store.snap)
			if err := test.create(store, "owner"); !errors.Is(err, errWebStoreConflict) {
				t.Fatalf("same-owner over-limit error = %v", err)
			}
			if err := test.create(store, "other"); err != nil {
				t.Fatalf("other owner was denied reserved capacity: %v", err)
			}
		})
	}
}
