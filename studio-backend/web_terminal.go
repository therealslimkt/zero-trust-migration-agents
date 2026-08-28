package main

// web_terminal.go owns the durable, source-scoped live terminal stream. Only
// the separately authenticated, loopback-only producer endpoint can admit
// frames; browsers receive an authenticated read-only SSE projection.

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"unicode"
)

const webTerminalSSEEvent = "terminal.frame"

const webTerminalProducerPath = "/internal/v1/terminal"

var (
	webTerminalFrameIDPattern = regexp.MustCompile(`^frm_[A-Za-z0-9]{12,64}$`)

	webTerminalCredentialPatterns = []*regexp.Regexp{
		regexp.MustCompile(`(?i)\b(?:authorization|proxy-authorization)\s*[:=]\s*(?:bearer|basic)\s+\S+`),
		regexp.MustCompile(`(?i)\b(?:api[-_ ]?key|access[-_ ]?token|refresh[-_ ]?token|id[-_ ]?token|client[-_ ]?secret|password|passwd|secret[-_ ]?key|private[-_ ]?key)\b\s*[:=]\s*["']?\S+`),
		regexp.MustCompile(`\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY)\s*=\s*\S+`),
		regexp.MustCompile(`(?i)(?:--(?:password|token|api-key|client-secret|secret)(?:=|\s+))\S+`),
		regexp.MustCompile(`-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----`),
		regexp.MustCompile(`(?i)"(?:private_key|client_secret|refresh_token)"\s*:`),
		regexp.MustCompile(`(?:AIza[0-9A-Za-z_-]{20,}|ya29\.[0-9A-Za-z._-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z_-]{20,})`),
		regexp.MustCompile(`\beyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\b`),
		regexp.MustCompile(`(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@`),
	}
	webTerminalReasoningPatterns = []*regexp.Regexp{
		regexp.MustCompile(`(?i)\bchain[- ]of[- ]thought\b`),
		regexp.MustCompile(`(?i)\b(?:hidden|internal) reasoning\b`),
		regexp.MustCompile(`(?i)\breasoning tokens?\b`),
		regexp.MustCompile(`(?i)\bscratchpad\b`),
		regexp.MustCompile(`(?i)</?think>`),
		regexp.MustCompile(`(?i)\b(?:system prompt|developer message)\b`),
	}

	// ErrWebTerminalFrameSuppressed is deliberately value-free so a producer
	// cannot accidentally reflect credential material into another log.
	ErrWebTerminalFrameSuppressed = errors.New("web terminal: frame suppressed")
	ErrWebTerminalFrameRejected   = errors.New("web terminal: frame rejected")

	webTerminalErrLoopback = &cpFault{
		Status: http.StatusForbidden, Slug: "terminal-loopback-required",
		Title: "Loopback connection required", Detail: "Terminal producers must connect from this host.",
	}
)

// WebTerminalFrameAdmission is the trusted producer input. Identity and both
// sequences are assigned by the durable store; Line is either retained exactly
// or the entire frame is suppressed before persistence.
type WebTerminalFrameAdmission struct {
	RunID              string
	SourceID           WebSourceID
	Timestamp          string
	Lane               WebTerminalLane
	Stream             WebTerminalStream
	Producer           string
	Tool               string
	Line               string
	Severity           WebTerminalSeverity
	EvidenceReferences []WebEvidenceReference
}

type webTerminalAdmissionRequest struct {
	SchemaVersion      string                 `json:"schemaVersion"`
	RunID              string                 `json:"runId"`
	SourceID           WebSourceID            `json:"sourceId"`
	Timestamp          string                 `json:"timestamp"`
	Lane               WebTerminalLane        `json:"lane"`
	Stream             WebTerminalStream      `json:"stream"`
	Producer           string                 `json:"producer"`
	Tool               string                 `json:"tool"`
	Line               string                 `json:"line"`
	Severity           WebTerminalSeverity    `json:"severity"`
	EvidenceReferences []WebEvidenceReference `json:"evidenceReferences"`
}

func webValidTerminalLane(lane WebTerminalLane) bool {
	switch lane {
	case "source", "edge", "compiler", "destination":
		return true
	default:
		return false
	}
}

func webValidTerminalStream(stream WebTerminalStream) bool {
	switch stream {
	case "command", "stdout", "stderr", "system", "metric":
		return true
	default:
		return false
	}
}

func webValidTerminalSeverity(severity WebTerminalSeverity) bool {
	switch severity {
	case "debug", "info", "warning", "error":
		return true
	default:
		return false
	}
}

func webSafeTerminalLine(line string) bool {
	if !webSafeBoundedText(line, 4096) {
		return false
	}
	for _, value := range line {
		if unicode.IsControl(value) || value == '\u2028' || value == '\u2029' ||
			(value >= '\u202a' && value <= '\u202e') || (value >= '\u2066' && value <= '\u2069') {
			return false
		}
	}
	return true
}

func webTerminalSensitive(text string) bool {
	for _, pattern := range webTerminalCredentialPatterns {
		if pattern.MatchString(text) {
			return true
		}
	}
	for _, pattern := range webTerminalReasoningPatterns {
		if pattern.MatchString(text) {
			return true
		}
	}
	return false
}

func webValidTerminalEvidence(references []WebEvidenceReference) bool {
	if references == nil || len(references) > 50 {
		return false
	}
	for _, reference := range references {
		if !cpArtifactIDRe.MatchString(reference.ArtifactID) || !cpEvidenceKinds[string(reference.Kind)] || !validWebDigest(reference.Digest) {
			return false
		}
	}
	return true
}

func webValidateTerminalAdmission(input WebTerminalFrameAdmission) (suppressed bool, valid bool) {
	if webTerminalSensitive(input.Producer) || webTerminalSensitive(input.Tool) || webTerminalSensitive(input.Line) {
		return true, false
	}
	if !webRunIDPattern.MatchString(input.RunID) {
		return false, false
	}
	if _, ok := cpCanonicalHostname(string(input.SourceID)); !ok {
		return false, false
	}
	if _, ok := cpParseStamp(input.Timestamp); !ok || !webValidTerminalLane(input.Lane) ||
		!webValidTerminalStream(input.Stream) || !webValidTerminalSeverity(input.Severity) ||
		!webSafeBoundedText(input.Producer, 120) || !webSafeBoundedText(input.Tool, 120) ||
		!webSafeTerminalLine(input.Line) || !webValidTerminalEvidence(input.EvidenceReferences) {
		return false, false
	}
	return false, true
}

func webValidateTerminalSnapshot(frames []*WebTerminalFrame, ownedRuns map[string]bool) error {
	if frames == nil || len(frames) > webMaxStoredTerminalFrames {
		return webCorrupt("terminal frame capacity exceeded")
	}
	frameIDs := make(map[string]bool, len(frames))
	runCounts := make(map[string]int)
	sourceCounts := make(map[string]int)
	laneCounts := make(map[string]int)
	previousTimestamps := make(map[string]string)
	for _, frame := range frames {
		if frame == nil || frame.SchemaVersion != WebSchemaVersion || !webTerminalFrameIDPattern.MatchString(frame.FrameID) || frameIDs[frame.FrameID] {
			return webCorrupt("malformed or duplicate terminal frame id")
		}
		frameIDs[frame.FrameID] = true
		if !ownedRuns[frame.RunID] {
			return webCorrupt("terminal frame references an unowned run")
		}
		if _, ok := cpCanonicalHostname(string(frame.SourceID)); !ok {
			return webCorrupt("terminal frame references an unknown source")
		}
		input := WebTerminalFrameAdmission{
			RunID: frame.RunID, SourceID: frame.SourceID, Timestamp: frame.Timestamp,
			Lane: frame.Lane, Stream: frame.Stream, Producer: frame.Producer, Tool: frame.Tool,
			Line: frame.Line, Severity: frame.Severity, EvidenceReferences: frame.EvidenceReferences,
		}
		if suppressed, valid := webValidateTerminalAdmission(input); suppressed || !valid {
			return webCorrupt("unsafe terminal frame")
		}

		runCounts[frame.RunID]++
		if runCounts[frame.RunID] > webMaxRunTerminalFrames || frame.GlobalSequence != int64(runCounts[frame.RunID]) {
			return webCorrupt("terminal global sequence is not contiguous")
		}
		sourceKey := frame.RunID + "\x00" + string(frame.SourceID)
		sourceCounts[sourceKey]++
		if sourceCounts[sourceKey] > webMaxSourceTerminalFrames {
			return webCorrupt("terminal source capacity exceeded")
		}
		laneKey := sourceKey + "\x00" + string(frame.Lane)
		laneCounts[laneKey]++
		if frame.LaneSequence != int64(laneCounts[laneKey]) {
			return webCorrupt("terminal lane sequence is not contiguous")
		}
		if previous := previousTimestamps[frame.RunID]; previous != "" {
			previousStamp, _ := cpParseStamp(previous)
			stamp, _ := cpParseStamp(frame.Timestamp)
			if stamp.Before(previousStamp) {
				return webCorrupt("terminal timestamps are not monotonic")
			}
		}
		previousTimestamps[frame.RunID] = frame.Timestamp
	}
	return nil
}

func webCloneTerminalFrame(frame WebTerminalFrame) WebTerminalFrame {
	out := frame
	out.EvidenceReferences = make([]WebEvidenceReference, len(frame.EvidenceReferences))
	copy(out.EvidenceReferences, frame.EvidenceReferences)
	return out
}

func webNewTerminalFrameID(existing map[string]bool) (string, error) {
	for attempt := 0; attempt < 4; attempt++ {
		raw := make([]byte, 12)
		if _, err := rand.Read(raw); err != nil {
			return "", ErrWebTerminalFrameRejected
		}
		frameID := "frm_" + hex.EncodeToString(raw)
		if !existing[frameID] {
			return frameID, nil
		}
	}
	return "", ErrWebTerminalFrameRejected
}

// AdmitTerminalFrame validates and durably appends one trusted producer frame.
// It never rewrites or redacts Line: unsafe, credential-bearing, or reasoning
// content causes the whole frame to be suppressed before the snapshot changes.
func (s *WebStateStore) AdmitTerminalFrame(input WebTerminalFrameAdmission) (WebTerminalFrame, error) {
	if s == nil {
		return WebTerminalFrame{}, ErrWebTerminalFrameRejected
	}
	if input.EvidenceReferences == nil {
		input.EvidenceReferences = []WebEvidenceReference{}
	}
	if suppressed, valid := webValidateTerminalAdmission(input); suppressed {
		return WebTerminalFrame{}, ErrWebTerminalFrameSuppressed
	} else if !valid {
		return WebTerminalFrame{}, ErrWebTerminalFrameRejected
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	owned := false
	for _, record := range s.snap.RunOwnerships {
		if record.RunID == input.RunID {
			owned = true
			break
		}
	}
	if !owned {
		return WebTerminalFrame{}, ErrWebTerminalFrameRejected
	}
	if len(s.snap.TerminalFrames) >= webMaxStoredTerminalFrames {
		return WebTerminalFrame{}, errWebStoreConflict
	}

	runCount, sourceCount, laneCount := 0, 0, 0
	var previousTimestamp string
	existingIDs := make(map[string]bool, len(s.snap.TerminalFrames))
	for _, existing := range s.snap.TerminalFrames {
		existingIDs[existing.FrameID] = true
		if existing.RunID != input.RunID {
			continue
		}
		runCount++
		previousTimestamp = existing.Timestamp
		if existing.SourceID == input.SourceID {
			sourceCount++
			if existing.Lane == input.Lane {
				laneCount++
			}
		}
	}
	if runCount >= webMaxRunTerminalFrames || sourceCount >= webMaxSourceTerminalFrames {
		return WebTerminalFrame{}, errWebStoreConflict
	}
	if previousTimestamp != "" {
		previous, _ := cpParseStamp(previousTimestamp)
		current, _ := cpParseStamp(input.Timestamp)
		if current.Before(previous) {
			return WebTerminalFrame{}, ErrWebTerminalFrameRejected
		}
	}
	frameID, err := webNewTerminalFrameID(existingIDs)
	if err != nil {
		return WebTerminalFrame{}, err
	}
	references := make([]WebEvidenceReference, len(input.EvidenceReferences))
	copy(references, input.EvidenceReferences)
	frame := WebTerminalFrame{
		SchemaVersion: WebSchemaVersion, FrameID: frameID, RunID: input.RunID, SourceID: input.SourceID,
		GlobalSequence: int64(runCount + 1), LaneSequence: int64(laneCount + 1), Timestamp: input.Timestamp,
		Lane: input.Lane, Stream: input.Stream, Producer: input.Producer, Tool: input.Tool, Line: input.Line,
		Severity: input.Severity, EvidenceReferences: references,
	}
	next, err := s.cloneLocked()
	if err != nil {
		return WebTerminalFrame{}, err
	}
	copied := webCloneTerminalFrame(frame)
	next.TerminalFrames = append(next.TerminalFrames, &copied)
	if err := s.commitLocked(next); err != nil {
		return WebTerminalFrame{}, err
	}
	return webCloneTerminalFrame(frame), nil
}

// TerminalFramesAfter returns an exact bounded replay for one source stream.
// A cursor belonging to another run or source is unknown rather than usable as
// a side channel.
func (s *WebStateStore) TerminalFramesAfter(runID string, sourceID WebSourceID, cursor string, limit int) ([]WebTerminalFrame, error) {
	if s == nil || !webRunIDPattern.MatchString(runID) || (cursor != "" && !webTerminalFrameIDPattern.MatchString(cursor)) || limit < 1 || limit > webMaxSSEReplay {
		return nil, ErrWebTerminalFrameRejected
	}
	if _, ok := cpCanonicalHostname(string(sourceID)); !ok {
		return nil, ErrWebTerminalFrameRejected
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	startFound := cursor == ""
	frames := make([]WebTerminalFrame, 0, limit)
	for _, frame := range s.snap.TerminalFrames {
		if frame.RunID != runID || frame.SourceID != sourceID {
			continue
		}
		if !startFound {
			if frame.FrameID == cursor {
				startFound = true
			}
			continue
		}
		frames = append(frames, webCloneTerminalFrame(*frame))
		if len(frames) == limit {
			break
		}
	}
	if !startFound {
		return nil, errWebStoreNotFound
	}
	return frames, nil
}

func (h *webBFFHandler) handleRunSourceTerminal(w http.ResponseWriter, r *http.Request) {
	if !webRequireMethod(w, r, http.MethodGet) {
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
	sourceID := r.PathValue("source_id")
	if _, known := cpCanonicalHostname(sourceID); !known || cpFindSource(run, sourceID) == nil {
		webWriteProblem(w, cpErrNotFound)
		return
	}
	if len(r.Header.Values("Last-Event-ID")) > 1 {
		webWriteProblem(w, cpErrInvalidCursor)
		return
	}
	cursor := r.Header.Get("Last-Event-ID")
	if cursor != "" && !webTerminalFrameIDPattern.MatchString(cursor) {
		webWriteProblem(w, cpErrInvalidCursor)
		return
	}
	frames, err := h.store.TerminalFramesAfter(run.RunID, WebSourceID(sourceID), cursor, webMaxSSEReplay)
	if errors.Is(err, errWebStoreNotFound) {
		webWriteProblem(w, cpErrUnknownCursor)
		return
	}
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
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
	for _, frame := range frames {
		select {
		case <-r.Context().Done():
			return
		default:
		}
		payload, marshalErr := json.Marshal(frame)
		if marshalErr != nil {
			return
		}
		fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n", frame.FrameID, webTerminalSSEEvent, payload)
		if flusher != nil {
			flusher.Flush()
		}
	}
}

func (h *webBFFHandler) authorizedTerminalProducer(r *http.Request) bool {
	if !h.terminalProducerEnabled || len(r.Header.Values("Authorization")) != 1 {
		return false
	}
	got := sha256.Sum256([]byte(r.Header.Get("Authorization")))
	return subtle.ConstantTimeCompare(got[:], h.terminalProducerAuth[:]) == 1
}

// handleTerminalAdmission is intentionally outside /api/web/v1. It accepts no
// browser identity or CORS flow: only the separately authenticated local
// orchestrator may submit observable tool/runtime lines.
func (h *webBFFHandler) handleTerminalAdmission(w http.ResponseWriter, r *http.Request) {
	if !h.authorizedTerminalProducer(r) {
		w.Header().Set("WWW-Authenticate", "Bearer")
		webWriteProblem(w, cpErrUnauthorized)
		return
	}
	if r.Header.Get("Origin") != "" || !isLoopbackRemoteAddr(r.RemoteAddr) {
		webWriteProblem(w, webTerminalErrLoopback)
		return
	}
	if !webRequireMethod(w, r, http.MethodPost) {
		return
	}
	var request webTerminalAdmissionRequest
	if err := webDecodeJSON(w, r, &request, webMaxJSONBody); err != nil {
		webWriteProblem(w, err)
		return
	}
	if request.SchemaVersion != WebSchemaVersion {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	frame, err := h.store.AdmitTerminalFrame(WebTerminalFrameAdmission{
		RunID: request.RunID, SourceID: request.SourceID, Timestamp: request.Timestamp,
		Lane: request.Lane, Stream: request.Stream, Producer: request.Producer, Tool: request.Tool,
		Line: request.Line, Severity: request.Severity, EvidenceReferences: request.EvidenceReferences,
	})
	if errors.Is(err, ErrWebTerminalFrameSuppressed) {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if errors.Is(err, ErrWebTerminalFrameRejected) {
		webWriteProblem(w, cpErrInvalidRequest)
		return
	}
	if errors.Is(err, errWebStoreConflict) {
		webWriteProblem(w, cpErrEventLimit)
		return
	}
	if err != nil {
		webWriteProblem(w, cpErrInternal)
		return
	}
	webWriteJSON(w, http.StatusCreated, frame)
}
