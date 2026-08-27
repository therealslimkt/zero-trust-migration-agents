package main

// web_runs.go serves the authenticated live-run surface of /api/web/v1 on
// top of the frozen durable control-plane store, reached in process through a
// narrow adapter. No HTTP hop and no service token is involved: the browser
// bearer token authenticates the user, and the BFF itself is the only caller
// of the store.
//
// Ownership lives in the web store, never in the frozen state: every run
// created here is bound to the verified UID, and any request for a run the
// caller does not own is answered exactly like a request for a run that does
// not exist. Portfolio names are namespaced per owner before they reach the
// frozen store, so one user's name choices can neither collide with nor
// reveal another user's runs.

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
)

// WebRunBackend is the in-process surface the BFF needs from the frozen
// control plane: create, read, ordered events, and the single approval
// decision. *cpStore satisfies it directly.
type WebRunBackend interface {
	CreateRunWithOwnership(req *cpCreateRequest, bind func(*ControlPlaneRun) error) (*ControlPlaneRun, error)
	WebRunSnapshot(runID string) (*ControlPlaneRun, []*ControlPlaneEvent, error)
	Approval(runID string) (*ControlPlaneApproval, error)
	Decide(runID string, req *cpApprovalRequest) (*ControlPlaneApproval, error)
}

// NewWebControlPlaneRunBackend adapts the frozen ControlPlaneHandler's
// durable store for in-process use. It forwards no Authorization material:
// the handler's service-token gate applies only to its own HTTP surface.
func NewWebControlPlaneRunBackend(handler *ControlPlaneHandler) (WebRunBackend, error) {
	if handler == nil || handler.store == nil {
		return nil, errors.New("web bff: a configured control plane handler is required")
	}
	return handler.store, nil
}

func (s *cpStore) CreateRunWithOwnership(req *cpCreateRequest, bind func(*ControlPlaneRun) error) (*ControlPlaneRun, error) {
	if bind == nil {
		return nil, cpErrInternal
	}
	return s.createRunWithPrecommit(req, bind)
}

// webScopedPortfolioName maps (owner, display name) onto the frozen
// portfolio-name namespace. The digest keeps names from different owners
// disjoint, keeps the browser display name out of the frozen store, and makes
// a duplicate active name conflict only within one owner's namespace.
func webScopedPortfolioName(ownerUID, portfolioName string) string {
	sum := sha256.Sum256([]byte("web-run\x00" + ownerUID + "\x00" + portfolioName))
	return "web" + hex.EncodeToString(sum[:30])
}

// ---------------------------------------------------------------------------
// Projections
// ---------------------------------------------------------------------------

func webEvidenceFromControlPlane(refs []ControlPlaneEvidence) []WebEvidenceReference {
	out := make([]WebEvidenceReference, 0, len(refs))
	for _, ref := range refs {
		out = append(out, WebEvidenceReference{
			ArtifactID: ref.ArtifactID,
			Kind:       WebEvidenceKind(ref.Kind),
			Digest:     ref.Digest,
		})
	}
	return out
}

// webSourceEvidence collects the evidence references recorded against one
// source across the stored event log, deduplicated in first-seen order.
func webSourceEvidence(events []*ControlPlaneEvent, sourceID string) []WebEvidenceReference {
	out := make([]WebEvidenceReference, 0)
	seen := make(map[ControlPlaneEvidence]bool)
	for _, event := range events {
		if event.SourceID != sourceID {
			continue
		}
		for _, ref := range event.EvidenceReferences {
			if seen[ref] {
				continue
			}
			seen[ref] = true
			out = append(out, WebEvidenceReference{
				ArtifactID: ref.ArtifactID,
				Kind:       WebEvidenceKind(ref.Kind),
				Digest:     ref.Digest,
			})
			if len(out) == 100 {
				return out
			}
		}
	}
	return out
}

func webSourceProgress(src ControlPlaneSource, events []*ControlPlaneEvent) WebLiveSourceProgress {
	return WebLiveSourceProgress{
		SourceID:           WebSourceID(src.SourceID),
		Hostname:           src.Hostname,
		State:              WebRunState(src.State),
		RecordsRead:        src.RecordsRead,
		RecordsWritten:     src.RecordsWritten,
		RecordsRejected:    src.RecordsRejected,
		PlanDigest:         src.PlanDigest,
		FailureCode:        src.FailureCode,
		EvidenceReferences: webSourceEvidence(events, src.SourceID),
	}
}

// webRunSummary projects one frozen run plus its ownership record onto the
// contract liveRunSummary. Ownership is always injected from the verified
// session record, never from the frozen state or the request.
func (h *webBFFHandler) webRunSummary(record WebRunOwnershipRecord, run *ControlPlaneRun, events []*ControlPlaneEvent) (WebLiveRunSummary, error) {
	sources := make([]WebLiveSourceProgress, 0, len(run.Sources))
	for _, src := range run.Sources {
		sources = append(sources, webSourceProgress(src, events))
	}
	return WebLiveRunSummary{
		SchemaVersion:       WebSchemaVersion,
		ExperienceMode:      ExperienceModeLive,
		DataClass:           DataClassPrivate,
		RunID:               run.RunID,
		PortfolioName:       record.PortfolioName,
		Owner:               record.Owner,
		State:               WebRunState(run.State),
		Sources:             sources,
		PortfolioPlanDigest: run.PortfolioPlanDigest,
		UpdatedAt:           run.UpdatedAt,
	}, nil
}

// webLiveRunEvent projects one stored event with its per-run 1-based
// sequence position.
func webLiveRunEvent(event *ControlPlaneEvent, sequence int64) WebLiveRunEvent {
	return WebLiveRunEvent{
		SchemaVersion:      WebSchemaVersion,
		EventID:            event.EventID,
		RunID:              event.RunID,
		Sequence:           sequence,
		Timestamp:          event.Timestamp,
		SourceID:           WebSourceID(event.SourceID),
		EventType:          event.EventType,
		State:              WebRunState(event.State),
		Summary:            event.Summary,
		EvidenceReferences: webEvidenceFromControlPlane(event.EvidenceReferences),
	}
}

// ownedRun resolves ownership before touching the frozen store. Unknown run,
// foreign run, and malformed identifier are all the same not-found problem.
func (h *webBFFHandler) ownedRun(w http.ResponseWriter, uid, runID string) (WebRunOwnershipRecord, *ControlPlaneRun, []*ControlPlaneEvent, bool) {
	if !webRunIDPattern.MatchString(runID) {
		webWriteProblem(w, cpErrNotFound)
		return WebRunOwnershipRecord{}, nil, nil, false
	}
	record, ok := h.store.RunOwnership(runID)
	if !ok || record.OwnerUID != uid {
		webWriteProblem(w, cpErrNotFound)
		return WebRunOwnershipRecord{}, nil, nil, false
	}
	run, events, err := h.runs.WebRunSnapshot(runID)
	if err != nil {
		webWriteProblem(w, cpErrNotFound)
		return WebRunOwnershipRecord{}, nil, nil, false
	}
	return record, run, events, true
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

func (h *webBFFHandler) handleRuns(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		h.handleListRuns(w, r)
	case http.MethodPost:
		h.handleCreateRun(w, r)
	default:
		w.Header().Set("Allow", "GET, POST")
		webWriteProblem(w, cpErrMethodNotAllowed)
	}
}

func (h *webBFFHandler) handleListRuns(w http.ResponseWriter, r *http.Request) {
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	records := h.store.RunOwnershipsForOwner(identity.Subject)
	runs := make([]WebLiveRunSummary, 0, len(records))
	for _, record := range records {
		run, events, err := h.runs.WebRunSnapshot(record.RunID)
		if err != nil {
			// A binding whose run is gone is unlistable rather than fatal;
			// the frozen store remains the authority for run existence.
			continue
		}
		summary, err := h.webRunSummary(record, run, events)
		if err != nil {
			webWriteProblem(w, cpErrInternal)
			return
		}
		runs = append(runs, summary)
		if len(runs) == 1000 {
			break
		}
	}
	webWriteJSON(w, http.StatusOK, WebListLiveRunsResponse{
		SchemaVersion: WebSchemaVersion,
		Runs:          runs,
	})
}

func (h *webBFFHandler) handleCreateRun(w http.ResponseWriter, r *http.Request) {
	if !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	var req WebCreateLiveRunRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion || !webValidPortfolioName(req.PortfolioName) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if !webSetupIDPattern.MatchString(req.CloudSetupID) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if err := webValidateSourceIDSet(req.Sources); err != nil {
		webWriteProblem(w, err)
		return
	}
	owner, ok := webIdentitySummaryFromVerified(identity)
	if !ok {
		webWriteProblem(w, webErrIdentityIncomplete)
		return
	}
	actor, ok := webActorForUID(identity.Subject)
	if !ok {
		webWriteProblem(w, webErrActorNotPermitted)
		return
	}
	// Unknown, foreign, and unverified setups are indistinguishable here.
	setup, found := h.store.CloudSetup(identity.Subject, req.CloudSetupID)
	if !found || setup.Status != webCloudSetupVerified {
		webWriteProblem(w, webErrCloudSetupNotVerified)
		return
	}

	descriptors := make([]cpSourceDescriptor, 0, len(cpCanonicalSources))
	for _, canonical := range cpCanonicalSources {
		descriptors = append(descriptors, cpSourceDescriptor{
			SourceID: canonical.SourceID,
			Hostname: canonical.Hostname,
		})
	}
	run, err := h.runs.CreateRunWithOwnership(&cpCreateRequest{
		SchemaVersion: cpSchemaVersion,
		PortfolioName: webScopedPortfolioName(identity.Subject, req.PortfolioName),
		Sources:       descriptors,
		RequestedBy:   actor,
	}, func(created *ControlPlaneRun) error {
		return h.store.PutRunOwnership(WebRunOwnershipRecord{RunID: created.RunID, OwnerUID: identity.Subject, PortfolioName: req.PortfolioName, Owner: owner, CreatedAt: created.CreatedAt})
	})
	if err != nil {
		webWriteProblem(w, err)
		return
	}
	record, found := h.store.RunOwnership(run.RunID)
	if !found || record.OwnerUID != identity.Subject {
		webWriteProblem(w, cpErrInternal)
		return
	}
	_, events, err := h.runs.WebRunSnapshot(run.RunID)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	summary, err := h.webRunSummary(record, run, events)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	webWriteJSON(w, http.StatusAccepted, summary)
}

// webValidateSourceIDSet accepts exactly the three canonical source IDs,
// each exactly once, in any order.
func webValidateSourceIDSet(sources []WebSourceID) error {
	if len(sources) != len(cpCanonicalSources) {
		return cpErrInvalidSources
	}
	seen := make(map[WebSourceID]bool, len(sources))
	for _, source := range sources {
		if _, ok := cpCanonicalHostname(string(source)); !ok || seen[source] {
			return cpErrInvalidSources
		}
		seen[source] = true
	}
	return nil
}

func (h *webBFFHandler) handleRunByID(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	record, run, events, ok := h.ownedRun(w, identity.Subject, r.PathValue("run_id"))
	if !ok {
		return
	}
	summary, err := h.webRunSummary(record, run, events)
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	webWriteJSON(w, http.StatusOK, summary)
}

func (h *webBFFHandler) handleRunSource(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	_, run, events, ok := h.ownedRun(w, identity.Subject, r.PathValue("run_id"))
	if !ok {
		return
	}
	sourceID := r.PathValue("source_id")
	if _, known := cpCanonicalHostname(sourceID); !known {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	src := cpFindSource(run, sourceID)
	if src == nil {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	// The replay detail is intentionally absent: this slice has no recorded
	// replay for a live source, and the response never fabricates one.
	webWriteJSON(w, http.StatusOK, WebLiveSourceResponse{
		SchemaVersion:   WebSchemaVersion,
		ExperienceMode:  ExperienceModeLive,
		DataClass:       DataClassPrivate,
		RunID:           run.RunID,
		State:           WebRunState(run.State),
		SourceID:        WebSourceID(src.SourceID),
		Hostname:        src.Hostname,
		SnapshotVersion: int64(len(events)),
		UpdatedAt:       run.UpdatedAt,
		Progress:        webSourceProgress(*src, events),
	})
}

// handleRunEvents replays the owner's stored events as SSE with per-run
// sequence numbers, honouring Last-Event-ID exactly: resumption starts
// strictly after the named event, and an unknown cursor is an error rather
// than a silent skip.
func (h *webBFFHandler) handleRunEvents(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	_, _, events, ok := h.ownedRun(w, identity.Subject, r.PathValue("run_id"))
	if !ok {
		return
	}
	if len(r.Header.Values("Last-Event-ID")) > 1 {
		webWriteProblem(w, cpErrInvalidCursor)
		return
	}
	cursor := r.Header.Get("Last-Event-ID")
	if cursor != "" && !webEventPattern.MatchString(cursor) {
		webWriteProblem(w, cpErrInvalidCursor)
		return
	}
	start := 0
	if cursor != "" {
		found := -1
		for i, event := range events {
			if event.EventID == cursor {
				found = i
				break
			}
		}
		if found < 0 {
			webWriteProblem(w, cpErrUnknownCursor)
			return
		}
		start = found + 1
	}
	end := len(events)
	if end-start > webMaxSSEReplay {
		end = start + webMaxSSEReplay
	}

	w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	flusher, _ := w.(http.Flusher)
	fmt.Fprintf(w, "retry: %d\n\n", webSSERetryMillis)
	if flusher != nil {
		flusher.Flush()
	}
	for i := start; i < end; i++ {
		select {
		case <-r.Context().Done():
			return
		default:
		}
		// Marshalling escapes newlines and markup, so no stored value can
		// forge SSE framing.
		payload, merr := json.Marshal(webLiveRunEvent(events[i], int64(i+1)))
		if merr != nil {
			return
		}
		fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n", events[i].EventID, events[i].EventType, payload)
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func (h *webBFFHandler) handleRunApproval(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodPost) {
		return
	}
	if !h.allowMutation(w, r) {
		return
	}
	identity, ok := h.authenticate(w, r)
	if !ok {
		return
	}
	_, run, _, ok := h.ownedRun(w, identity.Subject, r.PathValue("run_id"))
	if !ok {
		return
	}
	// The contract approval body has no actor field; the strict decoder
	// rejects any spoofed one as an unknown field.
	var req WebLiveApprovalRequest
	if err := webDecodeJSON(w, r, &req, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if req.SchemaVersion != WebSchemaVersion {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if req.Decision != "approve" && req.Decision != "reject" {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if !validWebDigest(req.PlanDigest) {
		webWriteProblem(w, cpErrInvalidDigest)
		return
	}
	// The actor is always the verified UID. A UID the frozen actor
	// vocabulary cannot represent is rejected, never coerced or substituted.
	actor, ok := webActorForUID(identity.Subject)
	if !ok {
		webWriteProblem(w, webErrActorNotPermitted)
		return
	}
	approval, err := h.runs.Decide(run.RunID, &cpApprovalRequest{
		SchemaVersion: cpSchemaVersion,
		PlanDigest:    req.PlanDigest,
		Decision:      req.Decision,
		DecidedBy:     actor,
		Reason:        req.Reason,
	})
	if err != nil {
		webWriteProblem(w, err)
		return
	}
	webWriteJSON(w, http.StatusOK, WebLiveApprovalResponse{
		SchemaVersion:  WebSchemaVersion,
		RunID:          approval.RunID,
		ApprovalID:     approval.ApprovalID,
		PlanDigest:     approval.PlanDigest,
		Decision:       approval.Decision,
		ResultingState: string(approval.ResultingState),
		DecidedAt:      approval.DecidedAt,
	})
}
