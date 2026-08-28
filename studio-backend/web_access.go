package main

// web_access.go is the hosted-draft invitation boundary. Firebase proves who
// signed in; this policy decides whether that verified identity is invited and
// whether it may mutate application state. The browser cannot assign a role.

import (
	"errors"
	"strings"
)

type WebAccessRole string

const (
	WebAccessRoleViewer WebAccessRole = "viewer"
	WebAccessRoleAdmin  WebAccessRole = "admin"
)

type WebAccessPolicy struct {
	allowed map[string]struct{}
	admins  map[string]struct{}
}

func webAccessEmails(raw string) (map[string]struct{}, error) {
	out := make(map[string]struct{})
	for _, candidate := range strings.Split(raw, ",") {
		email := strings.ToLower(strings.TrimSpace(candidate))
		if email == "" {
			continue
		}
		if !webValidEmail(email) || strings.ContainsAny(candidate, "\r\n") {
			return nil, errors.New("web access: invalid email allowlist")
		}
		out[email] = struct{}{}
	}
	return out, nil
}

func NewWebAccessPolicy(allowedRaw, adminRaw string) (*WebAccessPolicy, error) {
	allowed, err := webAccessEmails(allowedRaw)
	if err != nil {
		return nil, err
	}
	admins, err := webAccessEmails(adminRaw)
	if err != nil {
		return nil, err
	}
	if len(allowed) == 0 || len(admins) == 0 {
		return nil, errors.New("web access: at least one invited user and admin are required")
	}
	for email := range admins {
		allowed[email] = struct{}{}
	}
	return &WebAccessPolicy{allowed: allowed, admins: admins}, nil
}

func (p *WebAccessPolicy) Authorize(identity WebVerifiedIdentity) (WebAccessRole, bool) {
	if p == nil || !identity.EmailVerified {
		return "", false
	}
	email := strings.ToLower(strings.TrimSpace(identity.Email))
	if _, ok := p.allowed[email]; !ok {
		return "", false
	}
	if _, ok := p.admins[email]; ok {
		return WebAccessRoleAdmin, true
	}
	return WebAccessRoleViewer, true
}
