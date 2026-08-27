package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

const WebMaxPublicationBytes = 8 << 20

// WebTrustedRunPublicationRecord must come from owner-controlled persistence,
// never from a browser request. It independently binds classification,
// completion, reconciliation, approval, run identity, and plan digest.
type WebTrustedRunPublicationRecord struct {
	SourceRunID           string
	DataClass             DataClass
	State                 WebRunState
	FullyReconciled       bool
	OwnerApprovalVerified bool
	PortfolioPlanDigest   string
}

// WebPublicationArtifactReader resolves immutable artifact bytes from trusted
// storage. The publisher re-hashes every body rather than trusting metadata.
type WebPublicationArtifactReader interface {
	ReadPublicationArtifact(ctx context.Context, sourceRunID, artifactID string) ([]byte, error)
}

type WebStoredDemo struct {
	DemoID       string
	BundleDigest string
	ManifestJSON []byte
}

// WebDemoPublicationStore atomically creates by DemoID or returns the existing
// immutable value. Implementations must never overwrite an existing DemoID
// and must atomically index a created value by both DemoID and BundleDigest.
type WebDemoPublicationStore interface {
	CreateOrGetPublishedDemo(ctx context.Context, candidate WebStoredDemo) (stored WebStoredDemo, created bool, err error)
}

type WebDemoPublisher struct {
	Artifacts WebPublicationArtifactReader
	Store     WebDemoPublicationStore
}

type WebPublishDemoInput struct {
	Manifest DemoManifest
	Trusted  WebTrustedRunPublicationRecord
}

type WebPublishDemoResult struct {
	DemoID       string
	BundleDigest string
	Location     string
	Created      bool
}

// Publish validates both untrusted manifest content and trusted server-side
// state, independently hashes evidence bodies, and performs an atomic
// create-only publication. Identical retries are idempotent.
func (publisher WebDemoPublisher) Publish(ctx context.Context, input WebPublishDemoInput) (WebPublishDemoResult, error) {
	if publisher.Artifacts == nil || publisher.Store == nil {
		return WebPublishDemoResult{}, webPublicationError("publisher_not_configured")
	}
	manifestJSON, err := json.Marshal(input.Manifest)
	if err != nil {
		return WebPublishDemoResult{}, webPublicationError("manifest_not_json_serializable")
	}
	if len(manifestJSON) > WebMaxPublicationBytes {
		return WebPublishDemoResult{}, webPublicationError("publication_too_large")
	}
	if err := ValidateDemoManifestForPublication(input.Manifest); err != nil {
		return WebPublishDemoResult{}, err
	}
	trusted := input.Trusted
	if trusted.SourceRunID != input.Manifest.SourceRunID {
		return WebPublishDemoResult{}, webPublicationError("trusted_run_mismatch")
	}
	if trusted.DataClass != DataClassSyntheticDemo {
		return WebPublishDemoResult{}, webPublicationError("trusted_classification_not_synthetic")
	}
	if trusted.State != "completed" {
		return WebPublishDemoResult{}, webPublicationError("trusted_run_not_completed")
	}
	if !trusted.FullyReconciled {
		return WebPublishDemoResult{}, webPublicationError("trusted_run_not_reconciled")
	}
	if !trusted.OwnerApprovalVerified {
		return WebPublishDemoResult{}, webPublicationError("trusted_owner_approval_missing")
	}
	if trusted.PortfolioPlanDigest != input.Manifest.PortfolioPlanDigest {
		return WebPublishDemoResult{}, webPublicationError("trusted_plan_digest_mismatch")
	}
	for _, reference := range input.Manifest.Evidence {
		body, err := publisher.Artifacts.ReadPublicationArtifact(ctx, input.Manifest.SourceRunID, reference.ArtifactID)
		if err != nil {
			return WebPublishDemoResult{}, webPublicationError("evidence_body_missing")
		}
		digest := sha256.Sum256(body)
		actual := "sha256:" + hex.EncodeToString(digest[:])
		if actual != reference.Digest {
			return WebPublishDemoResult{}, webPublicationError("evidence_body_digest_mismatch")
		}
	}
	candidate := WebStoredDemo{
		DemoID: input.Manifest.DemoID, BundleDigest: input.Manifest.BundleDigest,
		ManifestJSON: append([]byte(nil), manifestJSON...),
	}
	stored, created, err := publisher.Store.CreateOrGetPublishedDemo(ctx, candidate)
	if err != nil {
		return WebPublishDemoResult{}, webPublicationError("publication_store_failed")
	}
	if stored.DemoID != candidate.DemoID {
		return WebPublishDemoResult{}, webPublicationError("publication_store_invalid")
	}
	if stored.BundleDigest != candidate.BundleDigest {
		return WebPublishDemoResult{}, webPublicationError("demo_id_already_published")
	}
	if !bytes.Equal(stored.ManifestJSON, candidate.ManifestJSON) {
		return WebPublishDemoResult{}, webPublicationError("publication_store_invalid")
	}
	return WebPublishDemoResult{
		DemoID: candidate.DemoID, BundleDigest: candidate.BundleDigest,
		Location: "/api/web/v1/demos/" + candidate.DemoID, Created: created,
	}, nil
}

func webPublicationError(code string) error {
	return &WebPublicationValidationError{Codes: []string{code}}
}
