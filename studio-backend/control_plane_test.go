package main

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

const cpTestToken = "test-control-plane-token"

func cpTestStatePath(t *testing.T) string {
	t.Helper()
	return filepath.Join(t.TempDir(), "state", "control-plane.json")
}

func cpTestHandler(t *testing.T, statePath string) *ControlPlaneHandler {
	t.Helper()
	h, err := NewControlPlaneHandler(statePath, cpTestToken)
	if err != nil {
		t.Fatalf("NewControlPlaneHandler: %v", err)
	}
	cp, ok := h.(*ControlPlaneHandler)
	if !ok {
		t.Fatalf("NewControlPlaneHandler returned %T, want *ControlPlaneHandler", h)
	}
	return cp
}

func cpTestNew(t *testing.T) *ControlPlaneHandler {
	t.Helper()
	return cpTestHandler(t, cpTestStatePath(t))
}

// cpTestDo issues an authenticated JSON request unless overrides say otherwise.
func cpTestDo(t *testing.T, h http.Handler, method, target, body string) *httptest.ResponseRecorder {
	t.Helper()
	var reader io.Reader
	if body != "" {
		reader = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, target, reader)
	req.Header.Set("Authorization", "Bearer "+cpTestToken)
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

const cpTestCreateBody = `{
  "schemaVersion": "1.0.0",
  "portfolioName": "Legacy ERP Portfolio",
  "sources": [
    {"sourceId": "jde", "hostname": "legacy-jde-db"},
    {"sourceId": "maxdb", "hostname": "legacy-maxdb"},
    {"sourceId": "btrieve", "hostname": "legacy-btrieve-db"}
  ],
  "requestedBy": "migration-operator"
}`

func cpTestCreate(t *testing.T, h http.Handler) cpRunBody {
	t.Helper()
	rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", cpTestCreateBody)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("create status = %d, want 202 (body %s)", rec.Code, rec.Body.String())
	}
	var run cpRunBody
	if err := json.Unmarshal(rec.Body.Bytes(), &run); err != nil {
		t.Fatalf("decode created run: %v", err)
	}
	return run
}

var cpTestPlanDigests = map[string]string{
	"jde":     "sha256:" + strings.Repeat("a", 64),
	"maxdb":   "sha256:" + strings.Repeat("b", 64),
	"btrieve": "sha256:" + strings.Repeat("c", 64),
}

// cpTestReachAwaitingApproval drives every source through the frozen sequence
// up to the single portfolio approval gate.
func cpTestReachAwaitingApproval(t *testing.T, h *ControlPlaneHandler, runID string) {
	t.Helper()
	for _, src := range []string{"jde", "maxdb", "btrieve"} {
		read := int64(100)
		steps := []struct {
			to  ControlPlaneState
			upd ControlPlaneSourceUpdate
		}{
			{ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}},
			{ControlPlaneStateRedacting, ControlPlaneSourceUpdate{
				ArtifactID: "art_" + src + "-manifest", Digest: cpTestPlanDigests[src], RecordsRead: &read,
			}},
			{ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
				ArtifactID: "art_" + src + "-redaction", Digest: cpTestPlanDigests[src],
			}},
		}
		for _, s := range steps {
			if _, err := h.AdvanceSource(runID, src, s.to, s.upd); err != nil {
				t.Fatalf("AdvanceSource(%s -> %s): %v", src, s.to, err)
			}
		}
		if _, err := h.AttachSourcePlan(runID, src, "art_"+src+"-plan-001", cpTestPlanDigests[src]); err != nil {
			t.Fatalf("AttachSourcePlan(%s): %v", src, err)
		}
	}
	if _, err := h.EnterAwaitingApproval(runID); err != nil {
		t.Fatalf("EnterAwaitingApproval: %v", err)
	}
}

// ---------------------------------------------------------------------------
// Construction and authentication
// ---------------------------------------------------------------------------

func TestNewControlPlaneHandler_RejectsUnusableConfiguration(t *testing.T) {
	cases := []struct {
		name  string
		path  string
		token string
	}{
		{"empty token", cpTestStatePath(t), ""},
		{"token with a space", cpTestStatePath(t), "bad token"},
		{"token with a control character", cpTestStatePath(t), "bad\ttoken"},
		{"token with non-ascii", cpTestStatePath(t), "tökén"},
		{"empty state path", "", cpTestToken},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if _, err := NewControlPlaneHandler(c.path, c.token); err == nil {
				t.Fatalf("expected an error for %s", c.name)
			}
		})
	}
}

func TestControlPlaneAuth_ExactBearerOnly(t *testing.T) {
	h := cpTestNew(t)

	cases := []struct {
		name    string
		headers []string
		want    int
	}{
		{"exact token", []string{"Bearer " + cpTestToken}, http.StatusAccepted},
		{"absent header", nil, http.StatusUnauthorized},
		{"empty header", []string{""}, http.StatusUnauthorized},
		{"wrong token", []string{"Bearer " + cpTestToken + "x"}, http.StatusUnauthorized},
		{"truncated token", []string{"Bearer " + cpTestToken[:5]}, http.StatusUnauthorized},
		{"lowercase scheme", []string{"bearer " + cpTestToken}, http.StatusUnauthorized},
		{"missing scheme", []string{cpTestToken}, http.StatusUnauthorized},
		{"double space", []string{"Bearer  " + cpTestToken}, http.StatusUnauthorized},
		{"trailing space", []string{"Bearer " + cpTestToken + " "}, http.StatusUnauthorized},
		{"other scheme", []string{"Basic " + cpTestToken}, http.StatusUnauthorized},
		{"duplicated header", []string{"Bearer " + cpTestToken, "Bearer " + cpTestToken}, http.StatusUnauthorized},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/v1/migrations", strings.NewReader(cpTestCreateBody))
			req.Header.Set("Content-Type", "application/json")
			for _, v := range c.headers {
				req.Header.Add("Authorization", v)
			}
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != c.want {
				t.Fatalf("status = %d, want %d", rec.Code, c.want)
			}
			if c.want == http.StatusUnauthorized {
				if got := rec.Header().Get("WWW-Authenticate"); got != "Bearer" {
					t.Errorf("WWW-Authenticate = %q, want %q", got, "Bearer")
				}
				cpAssertProblem(t, rec, http.StatusUnauthorized)
			}
			// Each accepted create must use a distinct portfolio name to
			// avoid the active-name conflict, so stop after the first.
			if c.want == http.StatusAccepted {
				h = cpTestNew(t)
			}
		})
	}
}

func TestControlPlaneAuth_AppliesToEveryEndpointAndUnknownPaths(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)

	targets := []struct{ method, path string }{
		{http.MethodPost, "/api/v1/migrations"},
		{http.MethodGet, "/api/v1/migrations/" + run.RunID},
		{http.MethodGet, "/api/v1/migrations/" + run.RunID + "/events"},
		{http.MethodPost, "/api/v1/migrations/" + run.RunID + "/approval"},
		{http.MethodGet, "/api/v1/migrations/" + run.RunID + "/secret"},
		{http.MethodGet, "/"},
	}
	for _, tc := range targets {
		req := httptest.NewRequest(tc.method, tc.path, strings.NewReader("{}"))
		req.Header.Set("Content-Type", "application/json")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Errorf("%s %s = %d, want 401", tc.method, tc.path, rec.Code)
		}
	}
}

// ---------------------------------------------------------------------------
// Method, media type and body limits
// ---------------------------------------------------------------------------

func TestControlPlane_MethodNotAllowed(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)

	cases := []struct{ method, path, allow string }{
		{http.MethodGet, "/api/v1/migrations", http.MethodPost},
		{http.MethodDelete, "/api/v1/migrations", http.MethodPost},
		{http.MethodPost, "/api/v1/migrations/" + run.RunID, http.MethodGet},
		{http.MethodPut, "/api/v1/migrations/" + run.RunID + "/events", http.MethodGet},
		{http.MethodGet, "/api/v1/migrations/" + run.RunID + "/approval", http.MethodPost},
	}
	for _, c := range cases {
		rec := cpTestDo(t, h, c.method, c.path, "")
		if rec.Code != http.StatusMethodNotAllowed {
			t.Errorf("%s %s = %d, want 405", c.method, c.path, rec.Code)
			continue
		}
		if got := rec.Header().Get("Allow"); got != c.allow {
			t.Errorf("%s %s Allow = %q, want %q", c.method, c.path, got, c.allow)
		}
		cpAssertProblem(t, rec, http.StatusMethodNotAllowed)
	}
}

func TestControlPlane_ContentTypeIsEnforced(t *testing.T) {
	h := cpTestNew(t)

	cases := []struct {
		name        string
		contentType []string
		want        int
	}{
		{"json", []string{"application/json"}, http.StatusAccepted},
		{"json with utf-8 charset", []string{"application/json; charset=utf-8"}, http.StatusAccepted},
		{"absent", nil, http.StatusUnsupportedMediaType},
		{"text", []string{"text/plain"}, http.StatusUnsupportedMediaType},
		{"form", []string{"application/x-www-form-urlencoded"}, http.StatusUnsupportedMediaType},
		{"json suffix type", []string{"application/vnd.api+json"}, http.StatusUnsupportedMediaType},
		{"wrong charset", []string{"application/json; charset=utf-16"}, http.StatusUnsupportedMediaType},
		{"unparseable", []string{"application/json; charset"}, http.StatusUnsupportedMediaType},
		{"duplicated header", []string{"application/json", "application/json"}, http.StatusUnsupportedMediaType},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if c.want == http.StatusAccepted {
				h = cpTestNew(t)
			}
			req := httptest.NewRequest(http.MethodPost, "/api/v1/migrations", strings.NewReader(cpTestCreateBody))
			req.Header.Set("Authorization", "Bearer "+cpTestToken)
			for _, v := range c.contentType {
				req.Header.Add("Content-Type", v)
			}
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)
			if rec.Code != c.want {
				t.Fatalf("status = %d, want %d", rec.Code, c.want)
			}
		})
	}
}

func TestControlPlane_BodyLimitIsEnforced(t *testing.T) {
	h := cpTestNew(t)
	oversized := fmt.Sprintf(`{"schemaVersion":"1.0.0","portfolioName":"%s","sources":[]}`,
		strings.Repeat("A", cpMaxRequestBody+1024))
	if len(oversized) <= cpMaxRequestBody {
		t.Fatalf("test body is not oversized")
	}
	rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", oversized)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", rec.Code)
	}
	cpAssertProblem(t, rec, http.StatusRequestEntityTooLarge)
}

func TestControlPlane_StrictBodies(t *testing.T) {
	h := cpTestNew(t)
	cases := []struct {
		name string
		body string
		want int
	}{
		{"unknown top-level field", `{"schemaVersion":"1.0.0","portfolioName":"P","sources":[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}],"extra":1}`, http.StatusBadRequest},
		{"unknown nested field", `{"schemaVersion":"1.0.0","portfolioName":"P","sources":[{"sourceId":"jde","hostname":"legacy-jde-db","port":1},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]}`, http.StatusBadRequest},
		{"trailing document", cpTestCreateBody + `{"schemaVersion":"1.0.0"}`, http.StatusBadRequest},
		{"not json", `not-json`, http.StatusBadRequest},
		{"empty body", `{}`, http.StatusBadRequest},
		{"wrong schema version", `{"schemaVersion":"2.0.0","portfolioName":"P","sources":[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]}`, http.StatusBadRequest},
		{"unsafe portfolio name", `{"schemaVersion":"1.0.0","portfolioName":"<script>","sources":[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]}`, http.StatusBadRequest},
		{"bad requester", `{"schemaVersion":"1.0.0","portfolioName":"P","requestedBy":" bad","sources":[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]}`, http.StatusBadRequest},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", c.body)
			if rec.Code != c.want {
				t.Fatalf("status = %d, want %d (body %s)", rec.Code, c.want, rec.Body.String())
			}
			cpAssertProblem(t, rec, c.want)
		})
	}
}

func TestControlPlane_InvalidSourceSets(t *testing.T) {
	h := cpTestNew(t)
	bodies := map[string]string{
		"missing a source":  `[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"}]`,
		"duplicated source": `[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]`,
		"unknown source":    `[{"sourceId":"oracle","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]`,
		"mismatched host":   `[{"sourceId":"jde","hostname":"legacy-maxdb"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]`,
		"ip hostname":       `[{"sourceId":"jde","hostname":"10.0.0.5"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"}]`,
		"four sources":      `[{"sourceId":"jde","hostname":"legacy-jde-db"},{"sourceId":"maxdb","hostname":"legacy-maxdb"},{"sourceId":"btrieve","hostname":"legacy-btrieve-db"},{"sourceId":"jde","hostname":"legacy-jde-db"}]`,
		"empty":             `[]`,
		"null":              `null`,
	}
	for name, sources := range bodies {
		t.Run(name, func(t *testing.T) {
			body := fmt.Sprintf(`{"schemaVersion":"1.0.0","portfolioName":"Portfolio","sources":%s}`, sources)
			rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", body)
			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400", rec.Code)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Create and get
// ---------------------------------------------------------------------------

func TestCreateAndGetMigration(t *testing.T) {
	h := cpTestNew(t)
	created := cpTestCreate(t, h)

	if created.SchemaVersion != cpSchemaVersion {
		t.Errorf("schemaVersion = %q", created.SchemaVersion)
	}
	if !cpRunIDRe.MatchString(created.RunID) {
		t.Errorf("runId %q does not match the frozen pattern", created.RunID)
	}
	if created.State != ControlPlaneStateCreated {
		t.Errorf("state = %q, want created", created.State)
	}
	if created.PortfolioName != "Legacy ERP Portfolio" {
		t.Errorf("portfolioName = %q", created.PortfolioName)
	}
	if created.PortfolioPlanDigest != "" {
		t.Errorf("a new portfolio must not carry a plan digest")
	}
	if len(created.Sources) != 3 {
		t.Fatalf("sources = %d, want 3", len(created.Sources))
	}
	for i, c := range cpCanonicalSources {
		got := created.Sources[i]
		if got.SourceID != c.SourceID || got.Hostname != c.Hostname {
			t.Errorf("source[%d] = %s/%s, want %s/%s", i, got.SourceID, got.Hostname, c.SourceID, c.Hostname)
		}
		if got.State != ControlPlaneStateCreated || got.RecordsRead != 0 {
			t.Errorf("source[%d] not in a fresh state: %+v", i, got)
		}
	}
	if created.CreatedAt == "" || created.UpdatedAt == "" {
		t.Errorf("timestamps missing: %+v", created)
	}

	// The internal requester binding must never reach the wire.
	got := cpTestDo(t, h, http.MethodGet, "/api/v1/migrations/"+created.RunID, "")
	if got.Code != http.StatusOK {
		t.Fatalf("get status = %d, want 200", got.Code)
	}
	var raw map[string]any
	if err := json.Unmarshal(got.Body.Bytes(), &raw); err != nil {
		t.Fatalf("decode: %v", err)
	}
	for _, forbidden := range []string{"requestedBy", "approvalId", "recordDigest", "planArtifactId"} {
		if _, present := raw[forbidden]; present {
			t.Errorf("contract run document leaked %q", forbidden)
		}
	}
	if raw["runId"] != created.RunID {
		t.Errorf("runId = %v, want %v", raw["runId"], created.RunID)
	}
}

func TestCreateMigration_ConflictsOnActiveDuplicateName(t *testing.T) {
	h := cpTestNew(t)
	cpTestCreate(t, h)
	rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", cpTestCreateBody)
	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409", rec.Code)
	}
	cpAssertProblem(t, rec, http.StatusConflict)
}

func TestGetMigration_NotFound(t *testing.T) {
	h := cpTestNew(t)
	for _, id := range []string{"mig_DOESNOTEXIST01", "not-a-run-id", "mig_short", "mig_has.a.dot0001", "MIG_UPPERCASE0001"} {
		rec := cpTestDo(t, h, http.MethodGet, "/api/v1/migrations/"+id, "")
		if rec.Code != http.StatusNotFound {
			t.Errorf("get %q = %d, want 404", id, rec.Code)
		}
	}
}

// ---------------------------------------------------------------------------
// Durability
// ---------------------------------------------------------------------------

func TestControlPlane_SurvivesRestart(t *testing.T) {
	path := cpTestStatePath(t)
	first := cpTestHandler(t, path)
	run := cpTestCreate(t, first)
	cpTestReachAwaitingApproval(t, first, run.RunID)

	before, err := first.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	eventsBefore, err := first.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events: %v", err)
	}

	second := cpTestHandler(t, path)
	after, err := second.Run(run.RunID)
	if err != nil {
		t.Fatalf("reloaded Run: %v", err)
	}
	if after.State != ControlPlaneStateAwaitingApproval {
		t.Errorf("reloaded state = %q, want awaiting_approval", after.State)
	}
	if after.PortfolioPlanDigest != before.PortfolioPlanDigest || after.PortfolioPlanDigest == "" {
		t.Errorf("plan digest did not survive restart: %q vs %q", after.PortfolioPlanDigest, before.PortfolioPlanDigest)
	}
	for i := range after.Sources {
		if after.Sources[i] != before.Sources[i] {
			t.Errorf("source %d changed across restart: %+v vs %+v", i, after.Sources[i], before.Sources[i])
		}
	}
	eventsAfter, err := second.Events(run.RunID)
	if err != nil {
		t.Fatalf("reloaded Events: %v", err)
	}
	if len(eventsAfter) != len(eventsBefore) {
		t.Fatalf("event count = %d, want %d", len(eventsAfter), len(eventsBefore))
	}
	for i := range eventsAfter {
		if eventsAfter[i].EventID != eventsBefore[i].EventID || eventsAfter[i].EventType != eventsBefore[i].EventType {
			t.Errorf("event %d changed across restart", i)
		}
	}

	// The reloaded handler must still accept the approval bound to the digest.
	body := fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve","decidedBy":"operator"}`,
		after.PortfolioPlanDigest)
	rec := cpTestDo(t, second, http.MethodPost, "/api/v1/migrations/"+run.RunID+"/approval", body)
	if rec.Code != http.StatusOK {
		t.Fatalf("approval after restart = %d, want 200 (%s)", rec.Code, rec.Body.String())
	}
}

func TestControlPlane_StateFileIsOwnerOnly(t *testing.T) {
	path := cpTestStatePath(t)
	h := cpTestHandler(t, path)

	assertMode := func(stage string) {
		t.Helper()
		info, err := os.Stat(path)
		if err != nil {
			t.Fatalf("%s: stat state: %v", stage, err)
		}
		if got := info.Mode().Perm(); got != 0o600 {
			t.Errorf("%s: state mode = %04o, want 0600", stage, got)
		}
	}
	assertMode("after construction")

	run := cpTestCreate(t, h)
	assertMode("after create")
	cpTestReachAwaitingApproval(t, h, run.RunID)
	assertMode("after transitions")

	// No temp files may be left behind by a completed write.
	entries, err := os.ReadDir(filepath.Dir(path))
	if err != nil {
		t.Fatalf("read state dir: %v", err)
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".tmp") {
			t.Errorf("temp file %q was left behind", e.Name())
		}
	}
}

func TestControlPlane_RefusesCorruptState(t *testing.T) {
	build := func(t *testing.T, mutate func(map[string]any)) string {
		t.Helper()
		path := cpTestStatePath(t)
		h := cpTestHandler(t, path)
		run := cpTestCreate(t, h)
		cpTestReachAwaitingApproval(t, h, run.RunID)

		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read state: %v", err)
		}
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			t.Fatalf("decode state: %v", err)
		}
		mutate(doc)
		out, err := json.Marshal(doc)
		if err != nil {
			t.Fatalf("encode state: %v", err)
		}
		if err := os.WriteFile(path, out, 0o600); err != nil {
			t.Fatalf("write state: %v", err)
		}
		return path
	}

	runsOf := func(doc map[string]any) []any { return doc["runs"].([]any) }
	eventsOf := func(doc map[string]any) []any { return doc["events"].([]any) }

	cases := []struct {
		name   string
		mutate func(map[string]any)
	}{
		{"unknown envelope field", func(d map[string]any) { d["shadowRuns"] = []any{} }},
		{"unknown run field", func(d map[string]any) {
			runsOf(d)[0].(map[string]any)["backdoor"] = true
		}},
		{"unsupported snapshot version", func(d map[string]any) { d["snapshotVersion"] = 99 }},
		{"unsupported contract version", func(d map[string]any) { d["schemaVersion"] = "2.0.0" }},
		{"duplicate run id", func(d map[string]any) {
			runs := runsOf(d)
			d["runs"] = append(runs, runs[0])
		}},
		{"duplicate event id", func(d map[string]any) {
			events := eventsOf(d)
			d["events"] = append(events, events[0])
		}},
		{"event referencing an unknown run", func(d map[string]any) {
			eventsOf(d)[1].(map[string]any)["runId"] = "mig_ORPHANEVENT01"
		}},
		{"approval unlinked from its run", func(d map[string]any) {
			runsOf(d)[0].(map[string]any)["approvalId"] = "apr_DANGLINGAPPROV1"
		}},
		{"run state not derivable from sources", func(d map[string]any) {
			runsOf(d)[0].(map[string]any)["state"] = "completed"
		}},
		{"tampered portfolio plan digest", func(d map[string]any) {
			runsOf(d)[0].(map[string]any)["portfolioPlanDigest"] = "sha256:" + strings.Repeat("f", 64)
		}},
		{"tampered source plan digest", func(d map[string]any) {
			run := runsOf(d)[0].(map[string]any)
			run["sources"].([]any)[0].(map[string]any)["planDigest"] = "sha256:" + strings.Repeat("e", 64)
		}},
		{"portfolio event carrying a source", func(d map[string]any) {
			eventsOf(d)[0].(map[string]any)["sourceId"] = "jde"
		}},
		{"unknown event type", func(d map[string]any) {
			eventsOf(d)[0].(map[string]any)["eventType"] = "operator.note"
		}},
		{"unsafe event summary", func(d map[string]any) {
			eventsOf(d)[0].(map[string]any)["summary"] = "<img src=x onerror=alert(1)>"
		}},
		{"non-canonical source", func(d map[string]any) {
			run := runsOf(d)[0].(map[string]any)
			run["sources"].([]any)[0].(map[string]any)["hostname"] = "10.0.0.5"
		}},
		{"negative counter", func(d map[string]any) {
			run := runsOf(d)[0].(map[string]any)
			run["sources"].([]any)[0].(map[string]any)["recordsRead"] = -1
		}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			path := build(t, c.mutate)
			if _, err := NewControlPlaneHandler(path, cpTestToken); err == nil {
				t.Fatalf("expected corrupt state to be refused")
			}
		})
	}

	t.Run("truncated file", func(t *testing.T) {
		path := cpTestStatePath(t)
		h := cpTestHandler(t, path)
		cpTestCreate(t, h)
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read: %v", err)
		}
		if err := os.WriteFile(path, raw[:len(raw)/2], 0o600); err != nil {
			t.Fatalf("write: %v", err)
		}
		if _, err := NewControlPlaneHandler(path, cpTestToken); err == nil {
			t.Fatalf("expected a truncated snapshot to be refused")
		}
	})
}

func TestControlPlane_CorruptStateErrorHidesPathsAndValues(t *testing.T) {
	path := cpTestStatePath(t)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(path, []byte(`{"snapshotVersion":1,"schemaVersion":"1.0.0","secretToken":"hunter2"}`), 0o600); err != nil {
		t.Fatalf("write: %v", err)
	}
	_, err := NewControlPlaneHandler(path, cpTestToken)
	if err == nil {
		t.Fatalf("expected refusal")
	}
	msg := err.Error()
	for _, leak := range []string{path, "hunter2", cpTestToken} {
		if strings.Contains(msg, leak) {
			t.Errorf("load error leaked %q: %s", leak, msg)
		}
	}
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

func TestPortfolioPlanDigest_MatchesPythonCanonicalVector(t *testing.T) {
	run := &ControlPlaneRun{
		RunID: "mig_DIGESTVECTOR01",
		Sources: []ControlPlaneSource{
			{SourceID: "jde", PlanDigest: "sha256:" + strings.Repeat("1", 64)},
			{SourceID: "maxdb", PlanDigest: "sha256:" + strings.Repeat("2", 64)},
			{SourceID: "btrieve", PlanDigest: "sha256:" + strings.Repeat("3", 64)},
		},
	}
	const expected = "sha256:e2288ef0c6e5ce4f8ffd669604e5bbf3f125d1142eba04f80954024608ab76e5"
	if got := cpPortfolioPlanDigest(run); got != expected {
		t.Fatalf("digest = %q, want shared canonical vector %q", got, expected)
	}
}

func TestOrchestration_ValidSequenceReachesCompletion(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)

	awaiting, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if awaiting.State != ControlPlaneStateAwaitingApproval {
		t.Fatalf("state = %q, want awaiting_approval", awaiting.State)
	}
	if awaiting.PortfolioPlanDigest == "" || !cpDigestRe.MatchString(awaiting.PortfolioPlanDigest) {
		t.Fatalf("portfolio plan digest = %q", awaiting.PortfolioPlanDigest)
	}

	body := fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve","decidedBy":"migration-operator"}`,
		awaiting.PortfolioPlanDigest)
	if rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations/"+run.RunID+"/approval", body); rec.Code != http.StatusOK {
		t.Fatalf("approve = %d (%s)", rec.Code, rec.Body.String())
	}

	for _, src := range []string{"jde", "maxdb", "btrieve"} {
		written := int64(100)
		steps := []struct {
			to  ControlPlaneState
			upd ControlPlaneSourceUpdate
		}{
			{ControlPlaneStateExecuting, ControlPlaneSourceUpdate{}},
			{ControlPlaneStateVerifying, ControlPlaneSourceUpdate{
				ArtifactID: "art_" + src + "-dataflow", Digest: cpTestPlanDigests[src], RecordsWritten: &written,
			}},
			{ControlPlaneStateCompleted, ControlPlaneSourceUpdate{
				ArtifactID: "art_" + src + "-recon-01", Digest: cpTestPlanDigests[src],
			}},
		}
		for _, s := range steps {
			if _, err := h.AdvanceSource(run.RunID, src, s.to, s.upd); err != nil {
				t.Fatalf("AdvanceSource(%s -> %s): %v", src, s.to, err)
			}
		}
	}

	final, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if final.State != ControlPlaneStateCompleted {
		t.Fatalf("final state = %q, want completed", final.State)
	}
	events, err := h.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events: %v", err)
	}
	if events[0].EventType != "migration.created" {
		t.Errorf("first event = %q, want migration.created", events[0].EventType)
	}
	if last := events[len(events)-1]; last.EventType != "migration.completed" || last.SourceID != "" {
		t.Errorf("last event = %+v, want a portfolio migration.completed", last)
	}
}

func TestOrchestration_InvalidTransitionsFailClosed(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	id := run.RunID

	t.Run("skipping a step", func(t *testing.T) {
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
			ArtifactID: "art_jde-redaction", Digest: cpTestPlanDigests["jde"],
		}); err == nil {
			t.Fatalf("expected a skipped step to be refused")
		}
	})
	t.Run("reserved target states", func(t *testing.T) {
		for _, to := range []ControlPlaneState{
			ControlPlaneStateAwaitingApproval, ControlPlaneStateApproved,
			ControlPlaneStateCancelled, ControlPlaneStateFailed, ControlPlaneStateCreated, "bogus",
		} {
			if _, err := h.AdvanceSource(id, "jde", to, ControlPlaneSourceUpdate{}); err == nil {
				t.Errorf("AdvanceSource to %q was accepted", to)
			}
		}
	})
	t.Run("unknown run and source", func(t *testing.T) {
		if _, err := h.AdvanceSource("mig_NOSUCHRUNXXXX", "jde", ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}); err == nil {
			t.Errorf("unknown run was accepted")
		}
		if _, err := h.AdvanceSource(id, "oracle", ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}); err == nil {
			t.Errorf("unknown source was accepted")
		}
	})
	t.Run("evidence is mandatory and bounded", func(t *testing.T) {
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}); err != nil {
			t.Fatalf("inventory start: %v", err)
		}
		bad := []ControlPlaneSourceUpdate{
			{},
			{ArtifactID: "art_jde-manifest"},
			{Digest: cpTestPlanDigests["jde"]},
			{ArtifactID: "bad-id", Digest: cpTestPlanDigests["jde"]},
			{ArtifactID: "art_jde-manifest", Digest: "not-a-digest"},
			{ArtifactID: "art_jde-manifest", Digest: "sha256:" + strings.Repeat("A", 64)},
		}
		for i, upd := range bad {
			if _, err := h.AdvanceSource(id, "jde", ControlPlaneStateRedacting, upd); err == nil {
				t.Errorf("case %d: bad evidence was accepted", i)
			}
		}
	})
	t.Run("counters never regress", func(t *testing.T) {
		read := int64(500)
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStateRedacting, ControlPlaneSourceUpdate{
			ArtifactID: "art_jde-manifest", Digest: cpTestPlanDigests["jde"], RecordsRead: &read,
		}); err != nil {
			t.Fatalf("inventory complete: %v", err)
		}
		lower := int64(1)
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
			ArtifactID: "art_jde-redaction", Digest: cpTestPlanDigests["jde"], RecordsRead: &lower,
		}); err == nil {
			t.Errorf("a regressing counter was accepted")
		}
		negative := int64(-1)
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
			ArtifactID: "art_jde-redaction", Digest: cpTestPlanDigests["jde"], RecordsRejected: &negative,
		}); err == nil {
			t.Errorf("a negative counter was accepted")
		}
	})
	t.Run("plan digests bind once", func(t *testing.T) {
		if _, err := h.AttachSourcePlan(id, "jde", "art_jde-plan-001", cpTestPlanDigests["jde"]); err == nil {
			t.Errorf("a plan attached to a non-planning source was accepted")
		}
		if _, err := h.AdvanceSource(id, "jde", ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
			ArtifactID: "art_jde-redaction", Digest: cpTestPlanDigests["jde"],
		}); err != nil {
			t.Fatalf("redaction complete: %v", err)
		}
		if _, err := h.AttachSourcePlan(id, "jde", "art_jde-plan-001", cpTestPlanDigests["jde"]); err != nil {
			t.Fatalf("AttachSourcePlan: %v", err)
		}
		if _, err := h.AttachSourcePlan(id, "jde", "art_jde-plan-002", cpTestPlanDigests["maxdb"]); err == nil {
			t.Errorf("a plan digest was allowed to be rebound")
		}
	})
	t.Run("approval gate needs every plan", func(t *testing.T) {
		if _, err := h.EnterAwaitingApproval(id); err == nil {
			t.Errorf("the approval gate opened with an incomplete plan set")
		}
	})
	t.Run("terminal runs are immutable", func(t *testing.T) {
		if _, err := h.FailSource(id, "maxdb", "SOURCE_UNREACHABLE"); err != nil {
			t.Fatalf("FailSource: %v", err)
		}
		failed, err := h.Run(id)
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if failed.State != ControlPlaneStateFailed || failed.FailureCode != "SOURCE_UNREACHABLE" {
			t.Fatalf("run = %q/%q, want failed/SOURCE_UNREACHABLE", failed.State, failed.FailureCode)
		}
		if _, err := h.AdvanceSource(id, "btrieve", ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}); err == nil {
			t.Errorf("a terminal portfolio accepted a transition")
		}
		if _, err := h.EnterAwaitingApproval(id); err == nil {
			t.Errorf("a terminal portfolio opened the approval gate")
		}
		if _, err := h.FailSource(id, "jde", "SOURCE_TIMEOUT"); err == nil {
			t.Errorf("a terminal portfolio accepted another failure")
		}
	})
	t.Run("failure codes are validated", func(t *testing.T) {
		other := cpTestNew(t)
		fresh := cpTestCreate(t, other)
		for _, code := range []string{"", "lowercase", "X", "<script>", strings.Repeat("A", 100)} {
			if _, err := other.FailSource(fresh.RunID, "jde", code); err == nil {
				t.Errorf("failure code %q was accepted", code)
			}
		}
	})
}

// ---------------------------------------------------------------------------
// Approval
// ---------------------------------------------------------------------------

func cpTestApprovalBody(digest, decision string) string {
	return fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":%q,"decidedBy":"migration-operator","reason":"Reviewed."}`,
		digest, decision)
}

func TestApproval_BindsExactDigestAndState(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	path := "/api/v1/migrations/" + run.RunID + "/approval"

	// A decision before the gate opens must conflict, not create one.
	early := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody("sha256:"+strings.Repeat("d", 64), "approve"))
	if early.Code != http.StatusConflict {
		t.Fatalf("early approval = %d, want 409", early.Code)
	}

	cpTestReachAwaitingApproval(t, h, run.RunID)
	current, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	digest := current.PortfolioPlanDigest

	t.Run("malformed digests are rejected", func(t *testing.T) {
		for _, bad := range []string{"", "deadbeef", "sha256:" + strings.Repeat("z", 64),
			"sha256:" + strings.Repeat("A", 64), "sha256:" + strings.Repeat("a", 63), "sha512:" + strings.Repeat("a", 64)} {
			rec := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody(bad, "approve"))
			if rec.Code != http.StatusBadRequest {
				t.Errorf("digest %q = %d, want 400", bad, rec.Code)
			}
		}
	})
	t.Run("a well-formed but stale digest conflicts", func(t *testing.T) {
		rec := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody("sha256:"+strings.Repeat("d", 64), "approve"))
		if rec.Code != http.StatusConflict {
			t.Errorf("stale digest = %d, want 409", rec.Code)
		}
		cpAssertProblem(t, rec, http.StatusConflict)
	})
	t.Run("invalid decisions and actors are rejected", func(t *testing.T) {
		bodies := []string{
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"maybe","decidedBy":"op"}`, digest),
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve"}`, digest),
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve","decidedBy":"<script>"}`, digest),
			fmt.Sprintf(`{"schemaVersion":"2.0.0","planDigest":%q,"decision":"approve","decidedBy":"op"}`, digest),
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve","decidedBy":"op","force":true}`, digest),
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":%q,"decision":"approve","decidedBy":"op","reason":"<b>no</b>"}`, digest),
		}
		for i, body := range bodies {
			rec := cpTestDo(t, h, http.MethodPost, path, body)
			if rec.Code != http.StatusBadRequest {
				t.Errorf("case %d = %d, want 400 (%s)", i, rec.Code, rec.Body.String())
			}
		}
	})

	// None of the refusals may have recorded a decision.
	if still, err := h.Run(run.RunID); err != nil || still.State != ControlPlaneStateAwaitingApproval {
		t.Fatalf("state after refusals = %v (%v), want awaiting_approval", still, err)
	}

	rec := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody(digest, "approve"))
	if rec.Code != http.StatusOK {
		t.Fatalf("approve = %d (%s)", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["schemaVersion"] != cpSchemaVersion || body["runId"] != run.RunID {
		t.Errorf("approval identity = %v", body)
	}
	if body["planDigest"] != digest {
		t.Errorf("planDigest = %v, want %v", body["planDigest"], digest)
	}
	if body["decision"] != "approve" || body["resultingState"] != string(ControlPlaneStateApproved) {
		t.Errorf("decision/resultingState = %v/%v", body["decision"], body["resultingState"])
	}
	if id, _ := body["approvalId"].(string); !cpApprovalIDRe.MatchString(id) {
		t.Errorf("approvalId = %v", body["approvalId"])
	}
	if _, leaked := body["reason"]; leaked {
		t.Errorf("the approval response echoed the caller reason")
	}

	after, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if after.State != ControlPlaneStateApproved {
		t.Errorf("state = %q, want approved", after.State)
	}
	for _, s := range after.Sources {
		if s.State != ControlPlaneStateApproved {
			t.Errorf("source %s = %q, want approved", s.SourceID, s.State)
		}
	}

	t.Run("replayed decisions conflict", func(t *testing.T) {
		for i := 0; i < 3; i++ {
			replay := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody(digest, "approve"))
			if replay.Code != http.StatusConflict {
				t.Fatalf("replay %d = %d, want 409", i, replay.Code)
			}
		}
		flip := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody(digest, "reject"))
		if flip.Code != http.StatusConflict {
			t.Fatalf("reversal = %d, want 409", flip.Code)
		}
		unchanged, err := h.Run(run.RunID)
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if unchanged.State != ControlPlaneStateApproved {
			t.Fatalf("state = %q, want approved to be immutable", unchanged.State)
		}
	})
}

func TestApproval_RejectionCancelsThePortfolio(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)
	current, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	path := "/api/v1/migrations/" + run.RunID + "/approval"

	rec := cpTestDo(t, h, http.MethodPost, path, cpTestApprovalBody(current.PortfolioPlanDigest, "reject"))
	if rec.Code != http.StatusOK {
		t.Fatalf("reject = %d (%s)", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["resultingState"] != string(ControlPlaneStateCancelled) {
		t.Errorf("resultingState = %v, want cancelled", body["resultingState"])
	}
	after, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if after.State != ControlPlaneStateCancelled {
		t.Fatalf("state = %q, want cancelled", after.State)
	}
	if _, err := h.AdvanceSource(run.RunID, "jde", ControlPlaneStateExecuting, ControlPlaneSourceUpdate{}); err == nil {
		t.Errorf("a cancelled portfolio accepted execution")
	}
	events, err := h.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events: %v", err)
	}
	types := make([]string, 0, 2)
	for _, ev := range events[len(events)-2:] {
		types = append(types, ev.EventType)
	}
	if strings.Join(types, ",") != "portfolio.rejected,migration.cancelled" {
		t.Errorf("tail events = %v", types)
	}
}

func TestApproval_UnknownRun(t *testing.T) {
	h := cpTestNew(t)
	rec := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations/mig_NOSUCHRUNXXXX/approval",
		cpTestApprovalBody("sha256:"+strings.Repeat("a", 64), "approve"))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

// ---------------------------------------------------------------------------
// Server-sent events
// ---------------------------------------------------------------------------

type cpSSEFrame struct {
	ID    string
	Event string
	Data  map[string]any
}

func cpParseSSE(t *testing.T, raw string) []cpSSEFrame {
	t.Helper()
	if raw == "" {
		return nil
	}
	var frames []cpSSEFrame
	for _, block := range strings.Split(strings.TrimRight(raw, "\n"), "\n\n") {
		var frame cpSSEFrame
		hasData := false
		for _, line := range strings.Split(block, "\n") {
			switch {
			case strings.HasPrefix(line, "retry: "):
			case strings.HasPrefix(line, "id: "):
				frame.ID = strings.TrimPrefix(line, "id: ")
			case strings.HasPrefix(line, "event: "):
				frame.Event = strings.TrimPrefix(line, "event: ")
			case strings.HasPrefix(line, "data: "):
				hasData = true
				if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "data: ")), &frame.Data); err != nil {
					t.Fatalf("SSE data is not JSON: %v", err)
				}
			default:
				t.Fatalf("unexpected SSE line %q", line)
			}
		}
		if hasData {
			frames = append(frames, frame)
		}
	}
	return frames
}

func cpTestStream(t *testing.T, h http.Handler, runID, cursor string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/migrations/"+runID+"/events", nil)
	req.Header.Set("Authorization", "Bearer "+cpTestToken)
	if cursor != "" {
		req.Header.Set("Last-Event-ID", cursor)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestSSE_PortfolioAndSourceShape(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)

	rec := cpTestStream(t, h, run.RunID, "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Errorf("Content-Type = %q", ct)
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "no-cache" {
		t.Errorf("Cache-Control = %q, want no-cache", cc)
	}
	if !strings.HasPrefix(rec.Body.String(), "retry: ") {
		t.Errorf("stream does not open with a reconnection hint")
	}

	frames := cpParseSSE(t, rec.Body.String())
	if len(frames) < 5 {
		t.Fatalf("frames = %d, want the full portfolio history", len(frames))
	}
	sawPortfolio, sawSource := false, false
	for i, f := range frames {
		if !cpEventIDRe.MatchString(f.ID) {
			t.Errorf("frame %d id = %q", i, f.ID)
		}
		scoped, known := cpEventSourceScoped[f.Event]
		if !known {
			t.Fatalf("frame %d event %q is outside the frozen vocabulary", i, f.Event)
		}
		if f.Data["eventId"] != f.ID || f.Data["eventType"] != f.Event {
			t.Errorf("frame %d id/type disagree with its data", i)
		}
		if f.Data["schemaVersion"] != cpSchemaVersion || f.Data["runId"] != run.RunID {
			t.Errorf("frame %d identity = %v", i, f.Data)
		}
		for _, required := range []string{"timestamp", "summary", "state", "evidenceReferences"} {
			if _, ok := f.Data[required]; !ok {
				t.Errorf("frame %d is missing %q", i, required)
			}
		}
		summary, _ := f.Data["summary"].(string)
		if !cpIsSafeText(summary, cpMaxSummaryRunes) {
			t.Errorf("frame %d summary is not safe text: %q", i, summary)
		}
		sourceID, hasSource := f.Data["sourceId"]
		if scoped {
			sawSource = true
			if !hasSource {
				t.Errorf("frame %d is source scoped but carries no sourceId", i)
			} else if _, ok := cpCanonicalHostname(sourceID.(string)); !ok {
				t.Errorf("frame %d sourceId = %v", i, sourceID)
			}
		} else {
			sawPortfolio = true
			if hasSource {
				t.Errorf("frame %d is portfolio scoped but carries a sourceId", i)
			}
		}
		refs, ok := f.Data["evidenceReferences"].([]any)
		if !ok {
			t.Fatalf("frame %d evidenceReferences is not a list", i)
		}
		for _, raw := range refs {
			ref := raw.(map[string]any)
			if !cpArtifactIDRe.MatchString(ref["artifactId"].(string)) {
				t.Errorf("frame %d artifactId = %v", i, ref["artifactId"])
			}
			if !cpEvidenceKinds[ref["kind"].(string)] {
				t.Errorf("frame %d evidence kind = %v", i, ref["kind"])
			}
			if !cpDigestRe.MatchString(ref["digest"].(string)) {
				t.Errorf("frame %d evidence digest = %v", i, ref["digest"])
			}
			if len(ref) != 3 {
				t.Errorf("frame %d evidence reference is not closed: %v", i, ref)
			}
		}
	}
	if !sawPortfolio || !sawSource {
		t.Errorf("stream did not carry both portfolio and source scoped events")
	}
	if frames[0].Event != "migration.created" {
		t.Errorf("first frame = %q, want migration.created", frames[0].Event)
	}
	if last := frames[len(frames)-1]; last.Event != "portfolio.awaiting_approval" {
		t.Errorf("last frame = %q, want portfolio.awaiting_approval", last.Event)
	}
}

func TestSSE_ResumesStrictlyAfterLastEventID(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)

	full := cpParseSSE(t, cpTestStream(t, h, run.RunID, "").Body.String())
	if len(full) < 4 {
		t.Fatalf("need a longer history, got %d", len(full))
	}

	for _, cut := range []int{0, 1, len(full) / 2, len(full) - 2} {
		rec := cpTestStream(t, h, run.RunID, full[cut].ID)
		if rec.Code != http.StatusOK {
			t.Fatalf("resume after %d = %d", cut, rec.Code)
		}
		got := cpParseSSE(t, rec.Body.String())
		want := full[cut+1:]
		if len(got) != len(want) {
			t.Fatalf("resume after %d returned %d frames, want %d", cut, len(got), len(want))
		}
		for i := range want {
			if got[i].ID != want[i].ID || got[i].Event != want[i].Event {
				t.Errorf("resume after %d frame %d = %s/%s, want %s/%s",
					cut, i, got[i].ID, got[i].Event, want[i].ID, want[i].Event)
			}
		}
	}

	// Resuming from the newest event yields nothing rather than replaying.
	tail := cpTestStream(t, h, run.RunID, full[len(full)-1].ID)
	if tail.Code != http.StatusOK {
		t.Fatalf("tail resume = %d", tail.Code)
	}
	if frames := cpParseSSE(t, tail.Body.String()); len(frames) != 0 {
		t.Errorf("tail resume replayed %d frames", len(frames))
	}
}

func TestSSE_UnknownCursorFailsRatherThanSkipping(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)

	other := cpTestDo(t, h, http.MethodPost, "/api/v1/migrations",
		strings.Replace(cpTestCreateBody, "Legacy ERP Portfolio", "Second Portfolio", 1))
	if other.Code != http.StatusAccepted {
		t.Fatalf("second create = %d", other.Code)
	}
	var second cpRunBody
	if err := json.Unmarshal(other.Body.Bytes(), &second); err != nil {
		t.Fatalf("decode: %v", err)
	}
	foreign := cpParseSSE(t, cpTestStream(t, h, second.RunID, "").Body.String())

	cases := []struct {
		name   string
		cursor string
		want   int
	}{
		{"well formed but unknown", "evt_UNKNOWNCURSOR1", http.StatusNotFound},
		{"belongs to another run", foreign[0].ID, http.StatusNotFound},
		{"malformed", "not-an-event-id", http.StatusBadRequest},
		{"wrong prefix", "mig_PORTFOLIO0001", http.StatusBadRequest},
		{"too short", "evt_short", http.StatusBadRequest},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			rec := cpTestStream(t, h, run.RunID, c.cursor)
			if rec.Code != c.want {
				t.Fatalf("status = %d, want %d", rec.Code, c.want)
			}
			cpAssertProblem(t, rec, c.want)
		})
	}

	t.Run("duplicated header", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/migrations/"+run.RunID+"/events", nil)
		req.Header.Set("Authorization", "Bearer "+cpTestToken)
		req.Header.Add("Last-Event-ID", foreign[0].ID)
		req.Header.Add("Last-Event-ID", "evt_UNKNOWNCURSOR1")
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Fatalf("status = %d, want 400", rec.Code)
		}
	})

	t.Run("unknown run", func(t *testing.T) {
		if rec := cpTestStream(t, h, "mig_NOSUCHRUNXXXX", ""); rec.Code != http.StatusNotFound {
			t.Fatalf("status = %d, want 404", rec.Code)
		}
	})
}

func TestSSE_ReplayIsBounded(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)
	cpTestReachAwaitingApproval(t, h, run.RunID)

	all, truncated, err := h.store.EventsAfter(run.RunID, "", 0)
	if err != nil {
		t.Fatalf("EventsAfter: %v", err)
	}
	if truncated {
		t.Fatalf("an unbounded read reported truncation")
	}
	limited, truncated, err := h.store.EventsAfter(run.RunID, "", 2)
	if err != nil {
		t.Fatalf("EventsAfter: %v", err)
	}
	if len(limited) != 2 || !truncated {
		t.Fatalf("limited read = %d frames, truncated=%v", len(limited), truncated)
	}
	if limited[0].EventID != all[0].EventID || limited[1].EventID != all[1].EventID {
		t.Errorf("a bounded replay must return the oldest unseen events first")
	}
	if cpMaxSSEReplay <= 0 {
		t.Errorf("the stream replay bound must be positive")
	}
}

// ---------------------------------------------------------------------------
// Concurrency
// ---------------------------------------------------------------------------

func TestControlPlane_ConcurrentMutationsAndReads(t *testing.T) {
	h := cpTestNew(t)
	run := cpTestCreate(t, h)

	var wg sync.WaitGroup
	for _, src := range []string{"jde", "maxdb", "btrieve"} {
		wg.Add(1)
		go func(src string) {
			defer wg.Done()
			read := int64(42)
			steps := []struct {
				to  ControlPlaneState
				upd ControlPlaneSourceUpdate
			}{
				{ControlPlaneStateInventorying, ControlPlaneSourceUpdate{}},
				{ControlPlaneStateRedacting, ControlPlaneSourceUpdate{
					ArtifactID: "art_" + src + "-manifest", Digest: cpTestPlanDigests[src], RecordsRead: &read,
				}},
				{ControlPlaneStatePlanning, ControlPlaneSourceUpdate{
					ArtifactID: "art_" + src + "-redaction", Digest: cpTestPlanDigests[src],
				}},
			}
			for _, s := range steps {
				if _, err := h.AdvanceSource(run.RunID, src, s.to, s.upd); err != nil {
					t.Errorf("AdvanceSource(%s -> %s): %v", src, s.to, err)
					return
				}
			}
			if _, err := h.AttachSourcePlan(run.RunID, src, "art_"+src+"-plan-001", cpTestPlanDigests[src]); err != nil {
				t.Errorf("AttachSourcePlan(%s): %v", src, err)
			}
		}(src)
	}
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if rec := cpTestDo(t, h, http.MethodGet, "/api/v1/migrations/"+run.RunID, ""); rec.Code != http.StatusOK {
				t.Errorf("concurrent get = %d", rec.Code)
			}
			if rec := cpTestStream(t, h, run.RunID, ""); rec.Code != http.StatusOK {
				t.Errorf("concurrent stream = %d", rec.Code)
			}
		}()
	}
	// Only one of many concurrent gate attempts may succeed.
	gateWins := make(chan bool, 4)
	for i := 0; i < 4; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := h.EnterAwaitingApproval(run.RunID)
			gateWins <- err == nil
		}()
	}
	wg.Wait()
	close(gateWins)
	opened := 0
	for ok := range gateWins {
		if ok {
			opened++
		}
	}
	if opened > 1 {
		t.Errorf("the approval gate opened %d times", opened)
	}

	final, err := h.Run(run.RunID)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if final.State != cpDeriveRunState(final.Sources) {
		t.Errorf("run state %q is not derivable from its sources", final.State)
	}
	events, err := h.Events(run.RunID)
	if err != nil {
		t.Fatalf("Events: %v", err)
	}
	seen := map[string]bool{}
	var prevSeq uint64
	for i, ev := range events {
		if seen[ev.EventID] {
			t.Errorf("duplicate event id %q", ev.EventID)
		}
		seen[ev.EventID] = true
		if i > 0 && ev.Seq <= prevSeq {
			t.Errorf("event %d is out of order", i)
		}
		prevSeq = ev.Seq
	}
	// The durable snapshot must reload cleanly after concurrent writes.
	if _, err := NewControlPlaneHandler(h.store.path, cpTestToken); err != nil {
		t.Fatalf("reload after concurrent mutations: %v", err)
	}
}

func TestCreateMigration_ConcurrentDuplicatesYieldOneRun(t *testing.T) {
	h := cpTestNew(t)
	const attempts = 8
	codes := make(chan int, attempts)
	var wg sync.WaitGroup
	for i := 0; i < attempts; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes <- cpTestDo(t, h, http.MethodPost, "/api/v1/migrations", cpTestCreateBody).Code
		}()
	}
	wg.Wait()
	close(codes)
	accepted := 0
	for c := range codes {
		switch c {
		case http.StatusAccepted:
			accepted++
		case http.StatusConflict:
		default:
			t.Errorf("unexpected status %d", c)
		}
	}
	if accepted != 1 {
		t.Fatalf("accepted %d creates, want exactly 1", accepted)
	}
}

// ---------------------------------------------------------------------------
// Problem responses
// ---------------------------------------------------------------------------

// cpAssertProblem verifies a closed problem document that leaks nothing.
func cpAssertProblem(t *testing.T, rec *httptest.ResponseRecorder, status int) {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); ct != "application/problem+json" {
		t.Errorf("Content-Type = %q, want application/problem+json", ct)
	}
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("problem body is not JSON: %v", err)
	}
	if body["schemaVersion"] != cpSchemaVersion {
		t.Errorf("schemaVersion = %v", body["schemaVersion"])
	}
	if got, ok := body["status"].(float64); !ok || int(got) != status {
		t.Errorf("status = %v, want %d", body["status"], status)
	}
	typ, _ := body["type"].(string)
	if !strings.HasPrefix(typ, cpProblemTypeBase) {
		t.Errorf("type = %q", typ)
	}
	title, _ := body["title"].(string)
	if title == "" || len([]rune(title)) > 120 {
		t.Errorf("title = %q", title)
	}
	for key := range body {
		switch key {
		case "schemaVersion", "type", "title", "status", "detail", "requestId":
		default:
			t.Errorf("problem document carries the unexpected field %q", key)
		}
	}
}

func TestProblemResponses_NeverEchoRequestOrSecrets(t *testing.T) {
	h := cpTestNew(t)
	const marker = "SENSITIVE-MARKER-VALUE"

	rejected := []struct {
		name   string
		method string
		path   string
		body   string
		auth   string
	}{
		{"bad token", http.MethodGet, "/api/v1/migrations/mig_DOESNOTEXIST01", "", "Bearer " + marker},
		{"unknown path", http.MethodGet, "/api/v1/migrations/mig_DOESNOTEXIST01/" + marker, "", "Bearer " + cpTestToken},
		{"invalid body", http.MethodPost, "/api/v1/migrations",
			fmt.Sprintf(`{"schemaVersion":"1.0.0","portfolioName":%q,"sources":[],"secret":%q}`, marker, marker),
			"Bearer " + cpTestToken},
		{"unparseable body", http.MethodPost, "/api/v1/migrations", `{"portfolioName": ` + marker, "Bearer " + cpTestToken},
		{"bad approval", http.MethodPost, "/api/v1/migrations/mig_DOESNOTEXIST01/approval",
			fmt.Sprintf(`{"schemaVersion":"1.0.0","planDigest":"sha256:%s","decision":"approve","decidedBy":%q}`,
				strings.Repeat("a", 64), marker),
			"Bearer " + cpTestToken},
	}
	for _, c := range rejected {
		t.Run(c.name, func(t *testing.T) {
			var reader io.Reader
			if c.body != "" {
				reader = strings.NewReader(c.body)
			}
			req := httptest.NewRequest(c.method, c.path, reader)
			req.Header.Set("Authorization", c.auth)
			if c.body != "" {
				req.Header.Set("Content-Type", "application/json")
			}
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, req)

			if rec.Code < 400 {
				t.Fatalf("status = %d, want a failure", rec.Code)
			}
			cpAssertProblem(t, rec, rec.Code)

			payload := rec.Body.String()
			for _, leak := range []string{marker, cpTestToken, h.store.path, "json:", "cannot unmarshal", ".go:"} {
				if strings.Contains(payload, leak) {
					t.Errorf("problem response leaked %q: %s", leak, payload)
				}
			}
		})
	}
}
