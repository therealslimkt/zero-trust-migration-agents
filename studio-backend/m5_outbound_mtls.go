package main

// m5_outbound_mtls.go defines the deliberately small boundary between a
// separately-operated outbound mTLS enrollment system and release authority.
//
// This file does not provision a CA, mint a client certificate, save a private
// key, open a network connection, or assert that a peer has been enrolled. It
// only validates a non-secret binding record supplied by such a system before
// a caller may associate it with one immutable M3 release command. Deployment
// composition remains responsible for resolving credentials and performing
// the actual mTLS handshake.

import (
	"errors"
	"regexp"
	"time"
)

const M5OutboundMTLSBindingSchemaVersion = "1.0.0"

var (
	ErrM5OutboundMTLSBindingInvalid  = errors.New("m5 outbound mtls: invalid binding")
	ErrM5OutboundMTLSBindingMismatch = errors.New("m5 outbound mtls: release binding mismatch")
	ErrM5OutboundMTLSBindingExpired  = errors.New("m5 outbound mtls: binding is not currently valid")

	// A server identity is a DNS name used as the TLS ServerName, never an
	// arbitrary URL, socket address, or caller-provided trust root. Requiring a
	// dot prevents a generic localhost/default identity from entering a release
	// binding. The deployment layer still has to use this exact name for TLS.
	m5OutboundMTLSServerNameRE = regexp.MustCompile(`^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)
)

// M5OutboundMTLSEnrollmentBinding is the non-secret, immutable reference to
// a client identity that an external enrollment authority has already
// established. It deliberately excludes certificate bytes, private keys,
// tokens, endpoints, CA material, and human identity.
//
// EnrollmentID is opaque to Keraun. It is correlation evidence only and must
// not be interpreted as proof that enrollment happened: the deployment
// integration must verify the real credential and peer separately.
type M5OutboundMTLSEnrollmentBinding struct {
	SchemaVersion                string    `json:"schemaVersion"`
	EnrollmentID                 string    `json:"enrollmentId"`
	TenantID                     string    `json:"tenantId"`
	RunID                        string    `json:"runId"`
	ApprovalID                   string    `json:"approvalId"`
	ReleaseID                    string    `json:"releaseId"`
	PlanDigest                   string    `json:"planDigest"`
	ArtifactDigest               string    `json:"artifactDigest"`
	ClientCertificateFingerprint string    `json:"clientCertificateFingerprint"`
	ServerName                   string    `json:"serverName"`
	NotBefore                    time.Time `json:"notBefore"`
	NotAfter                     time.Time `json:"notAfter"`
}

// M5ValidateOutboundMTLSReleaseBinding validates that a release command is
// exactly the release pre-bound by the enrollment authority. It has no side
// effects; in particular, a successful return does not connect to a service,
// load a credential, or create a release. CreateRelease remains the M3
// authority for the signed-release transaction.
func M5ValidateOutboundMTLSReleaseBinding(binding M5OutboundMTLSEnrollmentBinding, release M3ReleaseCommand, now time.Time) error {
	if !m5ValidOutboundMTLSBinding(binding) {
		return ErrM5OutboundMTLSBindingInvalid
	}
	if now.IsZero() || now.Before(binding.NotBefore) || !now.Before(binding.NotAfter) {
		return ErrM5OutboundMTLSBindingExpired
	}
	if binding.TenantID != release.TenantID || binding.RunID != release.RunID ||
		binding.ApprovalID != release.ApprovalID || binding.ReleaseID != release.ReleaseID ||
		binding.PlanDigest != release.SubjectDigest || binding.ArtifactDigest != release.ArtifactDigest {
		return ErrM5OutboundMTLSBindingMismatch
	}
	return nil
}

func m5ValidOutboundMTLSBinding(binding M5OutboundMTLSEnrollmentBinding) bool {
	return binding.SchemaVersion == M5OutboundMTLSBindingSchemaVersion &&
		m3IdempotencyRE.MatchString(binding.EnrollmentID) &&
		m3ValidateScope(binding.TenantID, binding.RunID) == nil &&
		m3ApprovalRE.MatchString(binding.ApprovalID) &&
		m3ReleaseRE.MatchString(binding.ReleaseID) &&
		m3DigestRE.MatchString(binding.PlanDigest) &&
		m3DigestRE.MatchString(binding.ArtifactDigest) &&
		m3DigestRE.MatchString(binding.ClientCertificateFingerprint) &&
		len(binding.ServerName) <= 253 && m5OutboundMTLSServerNameRE.MatchString(binding.ServerName) &&
		!binding.NotBefore.IsZero() && !binding.NotAfter.IsZero() && binding.NotBefore.Before(binding.NotAfter)
}
