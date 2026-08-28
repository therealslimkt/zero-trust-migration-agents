package main

// web_identity.go verifies browser identity for the /api/web/v1 BFF.
//
// Every live operation authenticates with exactly one Identity Platform ID
// token presented as exactly one "Authorization: Bearer <token>" header. The
// token is verified through an injectable WebIdentityVerifier; production
// wiring uses the official Firebase Admin SDK verifier so signature, issuer,
// audience, and expiry checks are never reimplemented here. The BFF trusts
// only the verified claims: no request body, header, or query value can name
// an identity, an owner, or an actor.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net"
	"net/http"
	"net/url"
	"strings"
	"unicode/utf8"

	firebaseauth "firebase.google.com/go/v4/auth"
)

// webMaxBearerBytes bounds the accepted encoded ID token length.
const webMaxBearerBytes = 4096

// localDemoWebToken is intentionally public and non-secret. It is accepted
// only when the process explicitly enables the loopback-only local demo
// profile; production continues to use Firebase verification.
const localDemoWebToken = "ztm-loopback-demo-v1"

// WebVerifiedIdentity is the caller identity extracted from one successfully
// verified ID token. Subject is the stable Identity Platform UID; the other
// fields are optional profile claims.
type WebVerifiedIdentity struct {
	Subject       string
	DisplayName   string
	Email         string
	EmailVerified bool
	PictureURL    string
	Role          WebAccessRole
}

// WebIdentityVerifier verifies one encoded ID token and returns the verified
// identity. Implementations must return an error for any token that is not
// currently valid; the BFF never distinguishes failure causes to callers.
type WebIdentityVerifier interface {
	VerifyWebIdentity(ctx context.Context, idToken string) (WebVerifiedIdentity, error)
}

type localDemoWebIdentityVerifier struct{}

func (localDemoWebIdentityVerifier) VerifyWebIdentity(_ context.Context, idToken string) (WebVerifiedIdentity, error) {
	if idToken != localDemoWebToken {
		return WebVerifiedIdentity{}, errWebTokenRejected
	}
	return WebVerifiedIdentity{
		Subject: "local-demo-operator", DisplayName: "Local Demo Operator", Email: "operator@local.demo", EmailVerified: true, Role: WebAccessRoleAdmin,
	}, nil
}

// errWebTokenRejected deliberately carries no verifier detail, so upstream
// error text (which may quote the token) can never reach a response.
var errWebTokenRejected = errors.New("web identity: token rejected")

// FirebaseWebIdentityVerifier is the production WebIdentityVerifier backed by
// the official Firebase Admin SDK ID-token verification.
type FirebaseWebIdentityVerifier struct {
	client *firebaseauth.Client
}

// NewFirebaseWebIdentityVerifier wraps an initialised Firebase Auth client.
func NewFirebaseWebIdentityVerifier(client *firebaseauth.Client) (*FirebaseWebIdentityVerifier, error) {
	if client == nil {
		return nil, errors.New("web identity: a Firebase Auth client is required")
	}
	return &FirebaseWebIdentityVerifier{client: client}, nil
}

// VerifyWebIdentity verifies signature, issuer, audience and expiry through
// the Admin SDK and projects only the profile claims this API uses.
func (v *FirebaseWebIdentityVerifier) VerifyWebIdentity(ctx context.Context, idToken string) (WebVerifiedIdentity, error) {
	token, err := v.client.VerifyIDTokenAndCheckRevoked(ctx, idToken)
	if err != nil || token == nil {
		return WebVerifiedIdentity{}, errWebTokenRejected
	}
	identity := WebVerifiedIdentity{Subject: token.UID}
	if name, ok := token.Claims["name"].(string); ok {
		identity.DisplayName = name
	}
	if email, ok := token.Claims["email"].(string); ok {
		identity.Email = email
	}
	if verified, ok := token.Claims["email_verified"].(bool); ok {
		identity.EmailVerified = verified
	}
	if picture, ok := token.Claims["picture"].(string); ok {
		identity.PictureURL = picture
	}
	return identity, nil
}

// webBearerToken accepts exactly one Authorization header of the exact form
// "Bearer <token>" where the token is non-empty, bounded, printable ASCII
// with no embedded whitespace. Anything else fails closed.
func webBearerToken(r *http.Request) (string, bool) {
	values := r.Header.Values("Authorization")
	if len(values) != 1 {
		return "", false
	}
	token, ok := strings.CutPrefix(values[0], "Bearer ")
	if !ok || token == "" || len(token) > webMaxBearerBytes {
		return "", false
	}
	for i := 0; i < len(token); i++ {
		if token[i] <= 0x20 || token[i] >= 0x7f {
			return "", false
		}
	}
	return token, true
}

// webValidSubject bounds a verified UID for storage and responses.
func webValidSubject(subject string) bool {
	return webSafeBoundedText(subject, 256)
}

// webValidEmail applies the contract identitySummary email bounds.
func webValidEmail(email string) bool {
	if len(email) < 3 || len(email) > 320 || !utf8.ValidString(email) {
		return false
	}
	for _, r := range email {
		if r <= 0x20 || r == 0x7f {
			return false
		}
	}
	return strings.Contains(email, "@")
}

// webValidHTTPSURL accepts an absolute https URL within maxLen bytes.
func webValidHTTPSURL(value string, maxLen int) bool {
	if value == "" || len(value) > maxLen || !utf8.ValidString(value) {
		return false
	}
	for _, r := range value {
		if r <= 0x20 || r == 0x7f {
			return false
		}
	}
	parsed, err := url.Parse(value)
	if err != nil || parsed.Scheme != "https" || parsed.Host == "" || parsed.User != nil {
		return false
	}
	host := strings.ToLower(parsed.Hostname())
	if host == "localhost" || strings.HasSuffix(host, ".localhost") || strings.HasSuffix(host, ".local") || strings.HasSuffix(host, ".internal") {
		return false
	}
	if ip := net.ParseIP(host); ip != nil && (!ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback()) {
		return false
	}
	return true
}

// webSafeBoundedText requires non-empty, valid UTF-8, control-character-free
// text within maxRunes runes. This matches the contract's public-text pattern.
func webSafeBoundedText(value string, maxRunes int) bool {
	if value == "" || !utf8.ValidString(value) {
		return false
	}
	if utf8.RuneCountInString(value) > maxRunes {
		return false
	}
	for _, r := range value {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return true
}

func webTruncateRunes(value string, maxRunes int) string {
	if utf8.RuneCountInString(value) <= maxRunes {
		return value
	}
	runes := []rune(value)
	return string(runes[:maxRunes])
}

// webIdentitySummaryFromVerified builds the contract identitySummary from
// verified claims only. A missing display name falls back to the email; an
// identity without a usable subject or email is not accepted for this API.
func webIdentitySummaryFromVerified(identity WebVerifiedIdentity) (WebIdentitySummary, bool) {
	if !webValidSubject(identity.Subject) || !webValidEmail(identity.Email) {
		return WebIdentitySummary{}, false
	}
	displayName := identity.DisplayName
	if !webSafeBoundedText(displayName, 200) {
		displayName = webTruncateRunes(identity.Email, 200)
	}
	if !webSafeBoundedText(displayName, 200) {
		return WebIdentitySummary{}, false
	}
	summary := WebIdentitySummary{
		Subject:     identity.Subject,
		DisplayName: displayName,
		Email:       identity.Email,
	}
	if webValidHTTPSURL(identity.PictureURL, 2000) {
		summary.PictureURL = identity.PictureURL
	}
	return summary, true
}

// webActorForUID derives the durable decision/requester actor recorded in the
// control plane from the verified UID. A UID outside the frozen actor
// vocabulary is rejected rather than coerced, so an unknown browser actor can
// never be recorded against a run.
func webActorForUID(uid string) (string, bool) {
	if !webValidSubject(uid) {
		return "", false
	}
	sum := sha256.Sum256([]byte("web-actor\x00" + uid))
	return "web_" + hex.EncodeToString(sum[:16]), true
}
