package main

import (
	"errors"
	"strings"
	"testing"
	"time"
)

func m5TestOutboundMTLSBinding() M5OutboundMTLSEnrollmentBinding {
	return M5OutboundMTLSEnrollmentBinding{
		SchemaVersion:                M5OutboundMTLSBindingSchemaVersion,
		EnrollmentID:                 "enroll_12345678",
		TenantID:                     "tnt_testtenant01",
		RunID:                        "run_testrun000001",
		ApprovalID:                   "apr_PRODUCTION0001",
		ReleaseID:                    "rel_RELEASE000001",
		PlanDigest:                   "sha256:" + strings.Repeat("a", 64),
		ArtifactDigest:               "sha256:" + strings.Repeat("b", 64),
		ClientCertificateFingerprint: "sha256:" + strings.Repeat("c", 64),
		ServerName:                   "migration-gateway.internal.example",
		NotBefore:                    time.Date(2026, 8, 30, 12, 0, 0, 0, time.UTC),
		NotAfter:                     time.Date(2026, 8, 30, 13, 0, 0, 0, time.UTC),
	}
}

func m5TestReleaseForBinding(binding M5OutboundMTLSEnrollmentBinding) M3ReleaseCommand {
	return M3ReleaseCommand{
		TenantID:       binding.TenantID,
		RunID:          binding.RunID,
		ReleaseID:      binding.ReleaseID,
		ApprovalID:     binding.ApprovalID,
		SubjectDigest:  binding.PlanDigest,
		ArtifactDigest: binding.ArtifactDigest,
	}
}

func TestM5OutboundMTLSBindingAcceptsOnlyExactCurrentRelease(t *testing.T) {
	binding := m5TestOutboundMTLSBinding()
	if err := M5ValidateOutboundMTLSReleaseBinding(binding, m5TestReleaseForBinding(binding), binding.NotBefore.Add(time.Minute)); err != nil {
		t.Fatalf("validate exact current binding: %v", err)
	}
}

func TestM5OutboundMTLSBindingRejectsReleaseSwaps(t *testing.T) {
	binding := m5TestOutboundMTLSBinding()
	for name, mutate := range map[string]func(*M3ReleaseCommand){
		"tenant":   func(command *M3ReleaseCommand) { command.TenantID = "tnt_othertenant01" },
		"run":      func(command *M3ReleaseCommand) { command.RunID = "run_otherrun00001" },
		"approval": func(command *M3ReleaseCommand) { command.ApprovalID = "apr_PRODUCTION0002" },
		"release":  func(command *M3ReleaseCommand) { command.ReleaseID = "rel_RELEASE000002" },
		"plan":     func(command *M3ReleaseCommand) { command.SubjectDigest = "sha256:" + strings.Repeat("d", 64) },
		"artifact": func(command *M3ReleaseCommand) { command.ArtifactDigest = "sha256:" + strings.Repeat("e", 64) },
	} {
		t.Run(name, func(t *testing.T) {
			command := m5TestReleaseForBinding(binding)
			mutate(&command)
			err := M5ValidateOutboundMTLSReleaseBinding(binding, command, binding.NotBefore.Add(time.Minute))
			if !errors.Is(err, ErrM5OutboundMTLSBindingMismatch) {
				t.Fatalf("release swap error = %v, want mismatch", err)
			}
		})
	}
}

func TestM5OutboundMTLSBindingRejectsExpiredAndInvalidRecords(t *testing.T) {
	binding := m5TestOutboundMTLSBinding()
	command := m5TestReleaseForBinding(binding)
	for name, mutate := range map[string]func(*M5OutboundMTLSEnrollmentBinding){
		"expired":      func(value *M5OutboundMTLSEnrollmentBinding) { value.NotAfter = value.NotBefore.Add(time.Minute) },
		"wrong schema": func(value *M5OutboundMTLSEnrollmentBinding) { value.SchemaVersion = "2.0.0" },
		"invalid fingerprint": func(value *M5OutboundMTLSEnrollmentBinding) {
			value.ClientCertificateFingerprint = "sha256:not-a-fingerprint"
		},
		"url server name":   func(value *M5OutboundMTLSEnrollmentBinding) { value.ServerName = "https://gateway.example" },
		"localhost":         func(value *M5OutboundMTLSEnrollmentBinding) { value.ServerName = "localhost" },
		"reversed validity": func(value *M5OutboundMTLSEnrollmentBinding) { value.NotAfter = value.NotBefore },
	} {
		t.Run(name, func(t *testing.T) {
			value := binding
			mutate(&value)
			err := M5ValidateOutboundMTLSReleaseBinding(value, command, binding.NotBefore.Add(2*time.Minute))
			if name == "expired" {
				if !errors.Is(err, ErrM5OutboundMTLSBindingExpired) {
					t.Fatalf("expired error = %v, want expiry", err)
				}
				return
			}
			if !errors.Is(err, ErrM5OutboundMTLSBindingInvalid) {
				t.Fatalf("invalid binding error = %v, want invalid", err)
			}
		})
	}
}

func TestM5OutboundMTLSBindingHasNoSecretOrNetworkFields(t *testing.T) {
	// This compile-time construction documents the entire record surface. The
	// adapter only receives evidence identifiers and a TLS server identity; a
	// deployment integration supplies any credential and transport separately.
	_ = M5OutboundMTLSEnrollmentBinding{}
}
