package main

// web_bff.go is the browser-facing /api/web/v1 handler for the contract in
// contracts/web/v1. It is additive: the frozen /api/v1 service-token API and
// its state are untouched.
//
// Design rules enforced here:
//
//   - Every live operation requires exactly one Identity Platform bearer
//     token verified through an injectable WebIdentityVerifier; ownership and
//     actors always derive from the verified UID, never from request content.
//   - Mutations are accepted only from allowed browser origins (or from
//     non-browser callers that present no Origin at all).
//   - Request bodies are bounded, strictly typed JSON with no unknown fields.
//   - Errors are closed application/problem+json documents built only from
//     compile-time constants; tokens, bodies, paths, and origins are never
//     echoed.
//   - Handler states are honest: nothing is reported verified, completed, or
//     successful unless the corresponding deterministic check actually ran
//     and passed.
//   - Cross-UID reads and mutations are answered exactly like requests for
//     resources that do not exist.

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	// webMaxJSONBody bounds every request body except demo publication.
	webMaxJSONBody = 64 << 10

	// webMaxSSEReplay bounds one SSE response; clients resume via
	// Last-Event-ID.
	webMaxSSEReplay = 500

	webSSERetryMillis = 2000

	// webDefaultSetupTTL bounds how long a cloud setup command and its
	// one-time receipt stay redeemable.
	webDefaultSetupTTL = 30 * time.Minute
)

// ---------------------------------------------------------------------------
// Closed problem vocabulary (web additions; frozen cp faults are reused)
// ---------------------------------------------------------------------------

var (
	webErrOriginNotAllowed = &cpFault{
		Status: http.StatusForbidden, Slug: "origin-not-allowed",
		Title:  "Origin not allowed",
		Detail: "Mutations are accepted from allowed browser origins only.",
	}
	webErrActorNotPermitted = &cpFault{
		Status: http.StatusForbidden, Slug: "actor-not-permitted",
		Title:  "Actor not permitted",
		Detail: "The verified identity cannot be recorded as an actor for this operation.",
	}
	webErrIdentityIncomplete = &cpFault{
		Status: http.StatusForbidden, Slug: "identity-incomplete",
		Title:  "Identity incomplete",
		Detail: "The verified identity does not carry the profile claims this API requires.",
	}
	webErrCloudSetupNotVerified = &cpFault{
		Status: http.StatusConflict, Slug: "cloud-setup-not-verified",
		Title:  "Cloud setup not verified",
		Detail: "This operation requires a verified cloud setup owned by the caller.",
	}
	webErrCloudReceiptInvalid = &cpFault{
		Status: http.StatusConflict, Slug: "cloud-receipt-invalid",
		Title:  "Cloud receipt invalid",
		Detail: "The receipt does not match the reviewed setup command for this setup.",
	}
	webErrCloudSetupExpired = &cpFault{
		Status: http.StatusGone, Slug: "cloud-setup-expired",
		Title:  "Cloud setup expired",
		Detail: "The setup command expired; request a new setup command.",
	}
	webErrCloudUnavailable = &cpFault{
		Status: http.StatusServiceUnavailable, Slug: "cloud-verification-unavailable",
		Title:  "Cloud verification unavailable",
		Detail: "Cloud capability verification is not configured on this deployment.",
	}
	webErrResearchNotCompleted = &cpFault{
		Status: http.StatusConflict, Slug: "research-not-completed",
		Title:  "Research not completed",
		Detail: "Driver approval requires completed research.",
	}
	webErrStaleEvidenceDigest = &cpFault{
		Status: http.StatusConflict, Slug: "stale-evidence-digest",
		Title:  "Stale evidence digest",
		Detail: "The supplied evidence digest does not match the completed research evidence.",
	}
	webErrUnknownDriverCandidate = &cpFault{
		Status: http.StatusConflict, Slug: "unknown-driver-candidate",
		Title:  "Unknown driver candidate",
		Detail: "The named candidate is not part of the completed research result.",
	}
	webErrDriverAlreadyApproved = &cpFault{
		Status: http.StatusConflict, Slug: "driver-already-approved",
		Title:  "Driver already approved",
		Detail: "This research already carries an immutable approved candidate.",
	}
	webErrPublicationRejected = &cpFault{
		Status: http.StatusUnprocessableEntity, Slug: "publication-rejected",
		Title:  "Publication rejected",
		Detail: "The demo manifest does not satisfy the publication gate.",
	}
	webErrDemoAlreadyPublished = &cpFault{
		Status: http.StatusConflict, Slug: "demo-id-already-published",
		Title:  "Demo already published",
		Detail: "This demo identifier is already bound to a different immutable bundle.",
	}
	webErrPublicationUnavailable = &cpFault{
		Status: http.StatusServiceUnavailable, Slug: "publication-unavailable",
		Title:  "Publication unavailable",
		Detail: "Demo publication is not configured on this deployment.",
	}
	webErrResearchUnavailable = &cpFault{
		Status: http.StatusServiceUnavailable, Slug: "research-unavailable",
		Title:  "Research unavailable",
		Detail: "Driver research is not configured on this deployment.",
	}
)

// webWriteProblem emits the closed contract problem document. Every field is
// a compile-time constant; caller-supplied values never reach it.
func webWriteProblem(w http.ResponseWriter, err error) {
	fault := cpErrInternal
	var typed *cpFault
	if errors.As(err, &typed) && typed != nil {
		fault = typed
	}
	var validation *WebPublicationValidationError
	if errors.As(err, &validation) {
		fault = webPublicationFault(validation)
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(fault.Status)
	webEncodeJSON(w, WebProblemDetails{
		SchemaVersion: WebSchemaVersion,
		Type:          cpProblemTypeBase + fault.Slug,
		Title:         fault.Title,
		Status:        fault.Status,
		Detail:        fault.Detail,
	})
}

// webPublicationFault maps machine-readable publisher codes onto the closed
// problem vocabulary without reflecting manifest content.
func webPublicationFault(validation *WebPublicationValidationError) *cpFault {
	for _, code := range validation.Codes {
		switch code {
		case "publication_too_large":
			return cpErrPayloadTooLarge
		case "demo_id_already_published":
			return webErrDemoAlreadyPublished
		case "publisher_not_configured":
			return webErrPublicationUnavailable
		case "publication_store_failed", "publication_store_invalid":
			return cpErrInternal
		}
	}
	return webErrPublicationRejected
}

func webEncodeJSON(w io.Writer, body any) {
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(true)
	_ = enc.Encode(body)
}

// ---------------------------------------------------------------------------
// Deterministic provider interfaces
// ---------------------------------------------------------------------------

// WebCloudCapabilityProber deterministically checks a customer project for
// the capabilities the migration requires and returns the missing ones. An
// empty slice means every capability was actually observed. Implementations
// must hold no long-lived key material for the customer project.
type WebCloudCapabilityProber interface {
	ProbeCloudCapabilities(ctx context.Context, projectID, region, datasetPrefix string) ([]string, error)
}

// WebDriverResearchFinding is what a research provider (production: Gemini
// grounded research) returns. The handler validates every field before it is
// stored or served; an invalid finding fails the task rather than being
// repaired.
type WebDriverResearchFinding struct {
	Model          string
	Candidates     []WebDriverCandidate
	EvidenceDigest string
}

// WebDriverResearcher performs one deterministic research request.
type WebDriverResearcher interface {
	ResearchDrivers(ctx context.Context, request WebDriverResearchRequest) (WebDriverResearchFinding, error)
}

// WebDriverArtifactFingerprinter obtains the approved driver artifact bytes
// from its official source and returns their sha256 content address.
// Implementations must only hash bytes; they must never execute, load, or
// unpack the artifact.
type WebDriverArtifactRegistry interface {
	FingerprintArtifactRegistryRemote(ctx context.Context, projectID string, candidate WebDriverCandidate) (string, error)
}

// WebLiveSourceDetailReader resolves the exact private replay detail captured
// for one owned run/source. Missing detail is represented by os.ErrNotExist;
// implementations must never synthesize a replacement.
type WebLiveSourceDetailReader interface {
	ReadLiveSourceDetail(ctx context.Context, runID, sourceID string) (*WebSourceReplay, error)
}

// ---------------------------------------------------------------------------
// Configuration and constructor
// ---------------------------------------------------------------------------

// WebBFFConfig wires the browser BFF. Verifier, Runs, and Store are required;
// the provider interfaces are optional and, when absent, the corresponding
// operations report honest incomplete/unavailable states instead of
// fabricating success.
type WebBFFConfig struct {
	Verifier WebIdentityVerifier
	Runs     WebRunBackend
	Store    *WebStateStore

	// Artifacts resolves trusted evidence bodies for demo publication.
	Artifacts WebPublicationArtifactReader
	// LiveDetails resolves captured source/compiler/destination detail.
	LiveDetails WebLiveSourceDetailReader

	CloudProber      WebCloudCapabilityProber
	DriverResearcher WebDriverResearcher
	DriverRegistry   WebDriverArtifactRegistry

	// SyntheticDemoRunIDs is a deployment-owned allowlist of completed control-
	// plane runs that may be considered for public demo publication. Browser
	// input can never classify a private run as synthetic.
	SyntheticDemoRunIDs []string

	// AllowedOrigins is the exact-match origin allowlist for mutations.
	// Empty falls back to the process-wide configured allowlist.
	AllowedOrigins []string

	// Now, RunAsync, and SetupTTL are injectable for deterministic tests.
	Now      func() time.Time
	RunAsync func(func()) bool
	SetupTTL time.Duration
}

type webBFFHandler struct {
	verifier       WebIdentityVerifier
	runs           WebRunBackend
	store          *WebStateStore
	artifacts      WebPublicationArtifactReader
	liveDetails    WebLiveSourceDetailReader
	cloudProber    WebCloudCapabilityProber
	researcher     WebDriverResearcher
	driverRegistry WebDriverArtifactRegistry
	syntheticRuns  map[string]struct{}
	allowedOrigins []string
	now            func() time.Time
	runAsync       func(func()) bool
	setupTTL       time.Duration
	mux            *http.ServeMux
}

// NewWebBFFHandler builds the complete /api/web/v1 handler. The returned
// handler is self-contained; the surrounding router mounts it at
// "/api/web/v1/".
func NewWebBFFHandler(cfg WebBFFConfig) (http.Handler, error) {
	if cfg.Verifier == nil {
		return nil, errors.New("web bff: an identity verifier is required")
	}
	if cfg.Runs == nil {
		return nil, errors.New("web bff: a run backend is required")
	}
	if cfg.Store == nil {
		return nil, errors.New("web bff: a state store is required")
	}
	syntheticRuns := make(map[string]struct{}, len(cfg.SyntheticDemoRunIDs))
	for _, runID := range cfg.SyntheticDemoRunIDs {
		runID = strings.TrimSpace(runID)
		if !webRunIDPattern.MatchString(runID) {
			return nil, errors.New("web bff: synthetic demo run allowlist contains an invalid run id")
		}
		syntheticRuns[runID] = struct{}{}
	}
	h := &webBFFHandler{
		verifier:       cfg.Verifier,
		runs:           cfg.Runs,
		store:          cfg.Store,
		artifacts:      cfg.Artifacts,
		liveDetails:    cfg.LiveDetails,
		cloudProber:    cfg.CloudProber,
		researcher:     cfg.DriverResearcher,
		driverRegistry: cfg.DriverRegistry,
		syntheticRuns:  syntheticRuns,
		allowedOrigins: cfg.AllowedOrigins,
		now:            cfg.Now,
		runAsync:       cfg.RunAsync,
		setupTTL:       cfg.SetupTTL,
		mux:            http.NewServeMux(),
	}
	if len(h.allowedOrigins) == 0 {
		h.allowedOrigins = allowedOrigins()
	}
	if h.now == nil {
		h.now = func() time.Time { return time.Now().UTC() }
	}
	if h.runAsync == nil {
		capacity := make(chan struct{}, 8)
		h.runAsync = func(task func()) bool {
			select {
			case capacity <- struct{}{}:
				go func() { defer func() { <-capacity }(); task() }()
				return true
			default:
				return false
			}
		}
	}
	if h.setupTTL <= 0 {
		h.setupTTL = webDefaultSetupTTL
	}

	h.mux.HandleFunc("/api/web/v1/session", h.handleSession)
	h.mux.HandleFunc("/api/web/v1/demos", h.handleDemoList)
	h.mux.HandleFunc("/api/web/v1/demos/{demo_id}", h.handleDemoByID)
	h.mux.HandleFunc("/api/web/v1/demo-bundles/{bundle_digest}", h.handleDemoByDigest)
	h.mux.HandleFunc("/api/web/v1/demo-publications", h.handlePublishDemo)
	h.mux.HandleFunc("/api/web/v1/runs", h.handleRuns)
	h.mux.HandleFunc("/api/web/v1/runs/{run_id}", h.handleRunByID)
	h.mux.HandleFunc("/api/web/v1/runs/{run_id}/sources/{source_id}", h.handleRunSource)
	h.mux.HandleFunc("/api/web/v1/runs/{run_id}/events", h.handleRunEvents)
	h.mux.HandleFunc("/api/web/v1/runs/{run_id}/approval", h.handleRunApproval)
	h.mux.HandleFunc("/api/web/v1/cloud/connection", h.handleCloudConnection)
	h.mux.HandleFunc("/api/web/v1/cloud/connection/setup", h.handleCloudSetup)
	h.mux.HandleFunc("/api/web/v1/cloud/connection/verify", h.handleCloudVerify)
	h.mux.HandleFunc("/api/web/v1/drivers/research", h.handleDriverResearchCreate)
	h.mux.HandleFunc("/api/web/v1/drivers/research/{research_id}", h.handleDriverResearchStatus)
	h.mux.HandleFunc("/api/web/v1/drivers/research/{research_id}/approval", h.handleDriverApproval)
	h.mux.HandleFunc("/", func(w http.ResponseWriter, _ *http.Request) {
		webWriteProblem(w, cpErrNotFound)
	})
	return h, nil
}

// ServeHTTP applies the uniform security headers before routing. Public demo
// handlers replace Cache-Control with their public caching policy.
func (h *webBFFHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	header := w.Header()
	header.Set("Cache-Control", "no-store")
	header.Set("X-Content-Type-Options", "nosniff")
	header.Set("Referrer-Policy", "no-referrer")
	header.Set("X-Frame-Options", "DENY")
	header.Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
	header.Set("Cross-Origin-Opener-Policy", "same-origin")
	header.Set("Cross-Origin-Resource-Policy", "same-origin")
	h.mux.ServeHTTP(w, r)
}

func (h *webBFFHandler) stamp(t time.Time) string {
	return t.UTC().Format(cpTimeFormat)
}

// ---------------------------------------------------------------------------
// Request gates
// ---------------------------------------------------------------------------

func webRequireMethod(w http.ResponseWriter, r *http.Request, methods ...string) bool {
	for _, method := range methods {
		if r.Method == method {
			return true
		}
	}
	w.Header().Set("Allow", strings.Join(methods, ", "))
	webWriteProblem(w, cpErrMethodNotAllowed)
	return false
}

// allowMutation fails closed for cross-site browser requests. A present
// Origin must exactly match the allowlist; an absent Origin is accepted only
// when fetch metadata does not contradict it (browsers always send Origin on
// cross-origin POSTs). The origin value is never reflected into headers or
// bodies.
func (h *webBFFHandler) allowMutation(w http.ResponseWriter, r *http.Request) bool {
	origins := r.Header.Values("Origin")
	if len(origins) > 1 {
		webWriteProblem(w, webErrOriginNotAllowed)
		return false
	}
	if len(origins) == 1 {
		if !isOriginAllowed(origins[0], h.allowedOrigins) {
			webWriteProblem(w, webErrOriginNotAllowed)
			return false
		}
		return true
	}
	switch strings.ToLower(r.Header.Get("Sec-Fetch-Site")) {
	case "", "same-origin", "none":
		return true
	default:
		webWriteProblem(w, webErrOriginNotAllowed)
		return false
	}
}

func (h *webBFFHandler) unauthorized(w http.ResponseWriter) {
	w.Header().Set("WWW-Authenticate", "Bearer")
	webWriteProblem(w, cpErrUnauthorized)
}

// authenticate verifies the exact-one bearer header and returns the verified
// identity. Verification failures are indistinguishable to the caller.
func (h *webBFFHandler) authenticate(w http.ResponseWriter, r *http.Request) (WebVerifiedIdentity, bool) {
	token, ok := webBearerToken(r)
	if !ok {
		h.unauthorized(w)
		return WebVerifiedIdentity{}, false
	}
	identity, err := h.verifier.VerifyWebIdentity(r.Context(), token)
	if err != nil {
		h.unauthorized(w)
		return WebVerifiedIdentity{}, false
	}
	if !webValidSubject(identity.Subject) {
		webWriteProblem(w, webErrIdentityIncomplete)
		return WebVerifiedIdentity{}, false
	}
	return identity, true
}

// ---------------------------------------------------------------------------
// Strict JSON bodies
// ---------------------------------------------------------------------------

// webDecodeJSON enforces the media type, the byte limit, and exactly one
// strict JSON document with no unknown fields.
func webDecodeJSON(w http.ResponseWriter, r *http.Request, dst any, maxBytes int64) error {
	if len(r.Header.Values("Content-Type")) != 1 || !cpIsJSONContentType(r.Header.Get("Content-Type")) {
		return cpErrUnsupportedMedia
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxBytes)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return cpBodyFault(err)
	}
	if err := dec.Decode(new(struct{})); !errors.Is(err, io.EOF) {
		return cpBodyFault(err)
	}
	return nil
}

func webWriteJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	webEncodeJSON(w, body)
}

// webValidPortfolioName applies the exact contract portfolioName rule:
// 1..120 runes of valid UTF-8 with no control characters.
func webValidPortfolioName(name string) bool {
	if name == "" || !utf8.ValidString(name) || utf8.RuneCountInString(name) > 120 {
		return false
	}
	for _, r := range name {
		if r < 0x20 || r == 0x7f {
			return false
		}
	}
	return true
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

func (h *webBFFHandler) handleSession(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	user, ok := webIdentitySummaryFromVerified(identity)
	if !ok {
		webWriteProblem(w, webErrIdentityIncomplete)
		return
	}
	webWriteJSON(w, http.StatusOK, WebSessionResponse{
		SchemaVersion: WebSchemaVersion,
		Authenticated: true,
		User:          user,
	})
}
