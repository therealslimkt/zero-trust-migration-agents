package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

type fixedAccessVerifier struct{ identity WebVerifiedIdentity }

func (v fixedAccessVerifier) VerifyWebIdentity(context.Context, string) (WebVerifiedIdentity, error) {
	return v.identity, nil
}

func TestWebAccessPolicySeparatesInvitedViewersAndAdmins(t *testing.T) {
	policy, err := NewWebAccessPolicy("friend@example.test, admin@example.test", "admin@example.test")
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name     string
		identity WebVerifiedIdentity
		role     WebAccessRole
		allowed  bool
	}{
		{name: "admin", identity: WebVerifiedIdentity{Email: "ADMIN@example.test", EmailVerified: true}, role: WebAccessRoleAdmin, allowed: true},
		{name: "viewer", identity: WebVerifiedIdentity{Email: "friend@example.test", EmailVerified: true}, role: WebAccessRoleViewer, allowed: true},
		{name: "uninvited", identity: WebVerifiedIdentity{Email: "other@example.test", EmailVerified: true}},
		{name: "unverified", identity: WebVerifiedIdentity{Email: "friend@example.test"}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			role, allowed := policy.Authorize(test.identity)
			if role != test.role || allowed != test.allowed {
				t.Fatalf("authorize = %q, %v; want %q, %v", role, allowed, test.role, test.allowed)
			}
		})
	}
}

func TestWebAccessPolicyRequiresAnAdminAndInvite(t *testing.T) {
	for _, input := range [][2]string{{"", ""}, {"friend@example.test", ""}, {"bad", "admin@example.test"}} {
		if _, err := NewWebAccessPolicy(input[0], input[1]); err == nil {
			t.Fatalf("policy unexpectedly accepted %q / %q", input[0], input[1])
		}
	}
}

func TestAuthenticateMakesInvitedViewerReadOnly(t *testing.T) {
	policy, err := NewWebAccessPolicy("friend@example.test", "admin@example.test")
	if err != nil {
		t.Fatal(err)
	}
	handler := &webBFFHandler{
		verifier:     fixedAccessVerifier{identity: WebVerifiedIdentity{Subject: "friend-uid", Email: "friend@example.test", EmailVerified: true}},
		accessPolicy: policy,
	}
	read := httptest.NewRequest(http.MethodGet, "/api/web/v1/session", nil)
	read.Header.Set("Authorization", "Bearer test-token")
	readResponse := httptest.NewRecorder()
	identity, ok := handler.authenticate(readResponse, read)
	if !ok || identity.Role != WebAccessRoleViewer {
		t.Fatalf("viewer read = %#v, %v, status %d", identity, ok, readResponse.Code)
	}

	mutation := httptest.NewRequest(http.MethodPost, "/api/web/v1/runs", nil)
	mutation.Header.Set("Authorization", "Bearer test-token")
	mutationResponse := httptest.NewRecorder()
	if _, ok := handler.authenticate(mutationResponse, mutation); ok || mutationResponse.Code != http.StatusForbidden {
		t.Fatalf("viewer mutation accepted=%v status=%d", ok, mutationResponse.Code)
	}
}
