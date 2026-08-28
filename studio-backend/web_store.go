package main

// web_store.go is the durable browser-BFF state store. It is deliberately a
// separate snapshot file from the frozen control-plane state: the web layer
// owns publication records, run ownership, cloud setup lifecycles, and driver
// research, while the frozen store remains the only authority for run state.
//
// The store follows the same durability discipline as the frozen control
// plane: every mutation is applied to a deep copy, re-validated, written
// atomically (0600 temp file, fsync, rename, parent directory fsync), and only
// then made visible. Loading refuses unknown fields, trailing data, duplicate
// identifiers, and any record that violates an invariant.
//
// Publications are create-only and are indexed by both demoId and
// bundleDigest inside one mutation, so the two indexes can never disagree and
// an existing publication can never be overwritten.

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	webSnapshotVersion = 3

	webMaxStoredPublications   = 100
	webMaxStoredOwnerships     = 1000
	webMaxStoredTrusted        = 1000
	webMaxStoredSetups         = 1000
	webMaxStoredResearch       = 1000
	webMaxStoredTerminalFrames = 10000
	webMaxRunTerminalFrames    = 3000
	webMaxSourceTerminalFrames = 1000
	webMaxOwnerOwnerships      = 100
	webMaxOwnerTrusted         = 100
	webMaxOwnerSetups          = 100
	webMaxOwnerResearch        = 100
	webMaxMissingCaps          = 100
)

// Cloud setup lifecycle states persisted by the store. The wire connection
// status "not_connected" is derived, never stored.
const (
	webCloudSetupPending   = "pending"
	webCloudSetupVerifying = "verifying"
	webCloudSetupVerified  = "verified"
	webCloudSetupDegraded  = "degraded"
)

// Driver research lifecycle states.
const (
	webResearchQueued    = "queued"
	webResearchRunning   = "running"
	webResearchCompleted = "completed"
	webResearchFailed    = "failed"
)

var (
	webSetupIDPattern       = regexp.MustCompile(`^setup_[A-Za-z0-9_-]{8,64}$`)
	webResearchIDPattern    = regexp.MustCompile(`^research_[A-Za-z0-9_-]{8,64}$`)
	webCandidateIDPattern   = regexp.MustCompile(`^drv_[A-Za-z0-9_-]{8,64}$`)
	webProjectIDPattern     = regexp.MustCompile(`^[a-z][a-z0-9-]{4,28}[a-z0-9]$`)
	webRegionPattern        = regexp.MustCompile(`^[a-z]+-[a-z]+[0-9]+$`)
	webDatasetPrefixPattern = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,63}$`)
	webReceiptHashPattern   = regexp.MustCompile(`^[a-f0-9]{64}$`)
	webNoncePattern         = regexp.MustCompile(`^[a-f0-9]{16,128}$`)
	webGeminiModelPattern   = regexp.MustCompile(`^gemini-3\.7-flash(?:-[A-Za-z0-9._-]+)?$`)
)

// errWebStoreCorrupt never carries a path, a value, or caller data.
var errWebStoreCorrupt = errors.New("web store: state snapshot is corrupt")

func webCorrupt(reason string) error {
	return errors.New("web store: state snapshot is corrupt: " + reason)
}

var errWebStoreConflict = errors.New("web store: record already exists")
var errWebStoreNotFound = errors.New("web store: record not found")
var errWebStoreInvalid = errors.New("web store: record rejected")
var errWebStoreExpired = errors.New("web store: record expired")
var errWebStoreReceipt = errors.New("web store: receipt rejected")

// WebPublicationRecord is one immutable published demo. Summary fields are
// extracted from the validated manifest at creation time so the anonymous
// list endpoint never re-parses full manifests.
type WebPublicationRecord struct {
	DemoID         string          `json:"demoId"`
	BundleDigest   string          `json:"bundleDigest"`
	Title          string          `json:"title"`
	SourceRunID    string          `json:"sourceRunId"`
	PublishedAt    string          `json:"publishedAt"`
	ManifestPath   string          `json:"manifestPath"`
	ManifestSHA256 string          `json:"manifestSha256"`
	ManifestJSON   json.RawMessage `json:"-"`
}

func (r *WebPublicationRecord) storedDemo(manifestJSON []byte) WebStoredDemo {
	return WebStoredDemo{
		DemoID:       r.DemoID,
		BundleDigest: r.BundleDigest,
		ManifestJSON: append([]byte(nil), manifestJSON...),
	}
}

// WebRunOwnershipRecord binds one live run to the verified UID that created
// it and preserves the browser-facing portfolio display name plus the owner
// identity injected into every run response.
type WebRunOwnershipRecord struct {
	RunID         string             `json:"runId"`
	OwnerUID      string             `json:"ownerUid"`
	PortfolioName string             `json:"portfolioName"`
	Owner         WebIdentitySummary `json:"owner"`
	CreatedAt     string             `json:"createdAt"`
}

// webTrustedPublicationRecord is the owner-controlled server-side record the
// publisher requires. It is never populated from a browser request.
type webTrustedPublicationRecord struct {
	OwnerUID              string      `json:"ownerUid"`
	SourceRunID           string      `json:"sourceRunId"`
	DataClass             DataClass   `json:"dataClass"`
	State                 WebRunState `json:"state"`
	FullyReconciled       bool        `json:"fullyReconciled"`
	OwnerApprovalVerified bool        `json:"ownerApprovalVerified"`
	PortfolioPlanDigest   string      `json:"portfolioPlanDigest"`
}

// WebCloudSetupRecord is one non-secret cloud setup lifecycle record. Only
// the SHA-256 of the one-time receipt is stored; the receipt itself, and any
// key material, never touches disk.
type WebCloudSetupRecord struct {
	SetupID             string   `json:"setupId"`
	OwnerUID            string   `json:"ownerUid"`
	ProjectID           string   `json:"projectId"`
	Region              string   `json:"region"`
	DatasetPrefix       string   `json:"datasetPrefix"`
	ResourcePrefix      string   `json:"resourcePrefix"`
	ServiceAccountName  string   `json:"serviceAccountName"`
	RepositoryName      string   `json:"repositoryName"`
	BucketName          string   `json:"bucketName"`
	CommandDigest       string   `json:"commandDigest"`
	ReceiptSHA256       string   `json:"receiptSha256"`
	Status              string   `json:"status"`
	CreatedAt           string   `json:"createdAt"`
	ExpiresAt           string   `json:"expiresAt"`
	VerifiedAt          string   `json:"verifiedAt,omitempty"`
	MissingCapabilities []string `json:"missingCapabilities,omitempty"`
}

// WebDriverResearchRecord is one async driver research task with its
// immutable approval, if any.
type WebDriverResearchRecord struct {
	ResearchID  string                     `json:"researchId"`
	OwnerUID    string                     `json:"ownerUid"`
	Status      string                     `json:"status"`
	Request     WebDriverResearchRequest   `json:"request"`
	CreatedAt   string                     `json:"createdAt"`
	UpdatedAt   string                     `json:"updatedAt"`
	Result      *WebDriverResearchResponse `json:"result,omitempty"`
	FailureCode string                     `json:"failureCode,omitempty"`
	Approval    *WebDriverApprovalResponse `json:"approval,omitempty"`
}

func (r *WebDriverResearchRecord) clone() WebDriverResearchRecord {
	out := *r
	if r.Result != nil {
		result := *r.Result
		result.Candidates = append([]WebDriverCandidate(nil), r.Result.Candidates...)
		for i := range result.Candidates {
			result.Candidates[i].Caveats = append([]string(nil), result.Candidates[i].Caveats...)
		}
		out.Result = &result
	}
	if r.Approval != nil {
		approval := *r.Approval
		out.Approval = &approval
	}
	return out
}

// webSnapshot is the versioned on-disk envelope for all web BFF state.
type webSnapshot struct {
	SnapshotVersion     int                            `json:"snapshotVersion"`
	SchemaVersion       string                         `json:"schemaVersion"`
	Publications        []*WebPublicationRecord        `json:"publications"`
	RunOwnerships       []*WebRunOwnershipRecord       `json:"runOwnerships"`
	TrustedPublications []*webTrustedPublicationRecord `json:"trustedPublications"`
	CloudSetups         []*WebCloudSetupRecord         `json:"cloudSetups"`
	DriverResearch      []*WebDriverResearchRecord     `json:"driverResearch"`
	TerminalFrames      []*WebTerminalFrame            `json:"terminalFrames"`
}

func webEmptySnapshot() *webSnapshot {
	return &webSnapshot{
		SnapshotVersion:     webSnapshotVersion,
		SchemaVersion:       WebSchemaVersion,
		Publications:        []*WebPublicationRecord{},
		RunOwnerships:       []*WebRunOwnershipRecord{},
		TrustedPublications: []*webTrustedPublicationRecord{},
		CloudSetups:         []*WebCloudSetupRecord{},
		DriverResearch:      []*WebDriverResearchRecord{},
		TerminalFrames:      []*WebTerminalFrame{},
	}
}

// WebStateStore owns the web snapshot and its file. Every exported operation
// holds the mutex for its whole duration.
type WebStateStore struct {
	mu            sync.Mutex
	path          string
	dir           string
	bundleDir     string
	bundleRel     string
	remote        *gcsObjectStore
	remoteObject  string
	generation    int64
	syncDirectory func(string) error
	snap          *webSnapshot
}

func webSyncDirectory(path string) error {
	dir, err := os.Open(path)
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}

// OpenWebStateStore loads or initialises the durable web snapshot. The path
// must be distinct from the frozen control-plane state path.
func OpenWebStateStore(statePath string) (*WebStateStore, error) {
	if strings.TrimSpace(statePath) == "" {
		return nil, errors.New("web store: a state path is required")
	}
	abs, err := filepath.Abs(statePath)
	if err != nil {
		return nil, errors.New("web store: state path cannot be resolved")
	}
	dir := filepath.Dir(abs)
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, errors.New("web store: state directory cannot be prepared")
	}
	bundleRel := filepath.Base(abs) + ".bundles"
	bundleDir := filepath.Join(dir, bundleRel)
	if err := os.MkdirAll(bundleDir, 0o700); err != nil {
		return nil, errors.New("web store: publication directory cannot be prepared")
	}
	if err := os.Chmod(bundleDir, 0o700); err != nil {
		return nil, errors.New("web store: publication directory cannot be secured")
	}
	s := &WebStateStore{
		path: abs, dir: dir, bundleDir: bundleDir, bundleRel: bundleRel,
		syncDirectory: webSyncDirectory,
	}

	raw, err := os.ReadFile(abs)
	switch {
	case err == nil:
		snap, derr := webDecodeSnapshot(raw)
		if derr != nil {
			return nil, derr
		}
		if derr := s.validatePublicationBodies(snap); derr != nil {
			return nil, derr
		}
		s.snap = snap
	case errors.Is(err, os.ErrNotExist):
		s.snap = webEmptySnapshot()
		if _, werr := s.persist(s.snap); werr != nil {
			return nil, errors.New("web store: initial state could not be written")
		}
	default:
		return nil, errors.New("web store: state could not be read")
	}
	if err := s.failInterruptedResearch(); err != nil {
		return nil, errors.New("web store: interrupted research could not be recovered")
	}
	return s, nil
}

func OpenHostedWebStateStore(ctx context.Context, remote *gcsObjectStore, object string) (*WebStateStore, error) {
	if remote == nil || strings.TrimSpace(object) == "" {
		return nil, errors.New("web store: hosted state configuration is required")
	}
	initial, err := json.Marshal(webEmptySnapshot())
	if err != nil {
		return nil, errors.New("web store: initial hosted state is invalid")
	}
	raw, generation, err := remote.loadOrCreate(ctx, object, initial)
	if err != nil {
		return nil, errors.New("web store: hosted state could not be loaded")
	}
	snap, err := webDecodeSnapshot(raw)
	if err != nil {
		return nil, err
	}
	bundleRel := filepath.Base(object) + ".bundles"
	s := &WebStateStore{remote: remote, remoteObject: object, generation: generation, bundleRel: bundleRel, snap: snap}
	if err := s.validatePublicationBodies(snap); err != nil {
		return nil, err
	}
	if err := s.failInterruptedResearch(); err != nil {
		return nil, errors.New("web store: interrupted research could not be recovered")
	}
	return s, nil
}

func (s *WebStateStore) failInterruptedResearch() error {
	interrupted := false
	now := time.Now().UTC()
	for _, record := range s.snap.DriverResearch {
		if record.Status != webResearchQueued && record.Status != webResearchRunning {
			continue
		}
		stamp := now
		if previous, ok := cpParseStamp(record.UpdatedAt); ok && !stamp.After(previous) {
			stamp = previous.Add(time.Millisecond)
		}
		record.Status = webResearchFailed
		record.FailureCode = "DRIVER_RESEARCH_INTERRUPTED"
		record.Result = nil
		record.Approval = nil
		record.UpdatedAt = stamp.Format(cpTimeFormat)
		interrupted = true
	}
	if !interrupted {
		return nil
	}
	renamed, err := s.persist(s.snap)
	if !renamed || err != nil {
		return errWebStoreCorrupt
	}
	return nil
}

func webDecodeSnapshot(raw []byte) (*webSnapshot, error) {
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	var snap webSnapshot
	if err := dec.Decode(&snap); err != nil {
		return nil, webCorrupt("state is not a strict snapshot document")
	}
	if err := dec.Decode(new(struct{})); !errors.Is(err, io.EOF) {
		return nil, webCorrupt("state carries trailing data")
	}
	if snap.Publications == nil {
		snap.Publications = []*WebPublicationRecord{}
	}
	if snap.RunOwnerships == nil {
		snap.RunOwnerships = []*WebRunOwnershipRecord{}
	}
	if snap.TrustedPublications == nil {
		snap.TrustedPublications = []*webTrustedPublicationRecord{}
	}
	if snap.CloudSetups == nil {
		snap.CloudSetups = []*WebCloudSetupRecord{}
	}
	if snap.DriverResearch == nil {
		snap.DriverResearch = []*WebDriverResearchRecord{}
	}
	if snap.TerminalFrames == nil {
		snap.TerminalFrames = []*WebTerminalFrame{}
	}
	if err := webValidateStoreSnapshot(&snap); err != nil {
		return nil, err
	}
	return &snap, nil
}

// persist writes snap atomically and durably with owner-only permissions.
func (s *WebStateStore) persist(snap *webSnapshot) (bool, error) {
	data, err := json.Marshal(snap)
	if err != nil {
		return false, err
	}
	if s.remote != nil {
		ctx, cancel := gcsOperationContext()
		defer cancel()
		generation, err := s.remote.write(ctx, s.remoteObject, data, s.generation, false)
		if err != nil {
			return false, err
		}
		s.generation = generation
		return true, nil
	}
	tmp, err := os.CreateTemp(s.dir, ".web-state-*.tmp")
	if err != nil {
		return false, err
	}
	name := tmp.Name()
	committed := false
	defer func() {
		if !committed {
			_ = os.Remove(name)
		}
	}()
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return false, err
	}
	if err := tmp.Close(); err != nil {
		return false, err
	}
	if err := os.Rename(name, s.path); err != nil {
		return false, err
	}
	committed = true

	return true, s.syncDirectory(s.dir)
}

// cloneLocked deep-copies the current snapshot. Caller must hold s.mu.
func (s *WebStateStore) cloneLocked() (*webSnapshot, error) {
	encoded, err := json.Marshal(s.snap)
	if err != nil {
		return nil, errWebStoreCorrupt
	}
	next := webEmptySnapshot()
	if err := json.Unmarshal(encoded, next); err != nil {
		return nil, errWebStoreCorrupt
	}
	if next.Publications == nil {
		next.Publications = []*WebPublicationRecord{}
	}
	if next.RunOwnerships == nil {
		next.RunOwnerships = []*WebRunOwnershipRecord{}
	}
	if next.TrustedPublications == nil {
		next.TrustedPublications = []*webTrustedPublicationRecord{}
	}
	if next.CloudSetups == nil {
		next.CloudSetups = []*WebCloudSetupRecord{}
	}
	if next.DriverResearch == nil {
		next.DriverResearch = []*WebDriverResearchRecord{}
	}
	if next.TerminalFrames == nil {
		next.TerminalFrames = []*WebTerminalFrame{}
	}
	return next, nil
}

// commitLocked validates, durably persists, and only then publishes next.
func (s *WebStateStore) commitLocked(next *webSnapshot) error {
	if err := webValidateStoreSnapshot(next); err != nil {
		return errWebStoreCorrupt
	}
	renamed, err := s.persist(next)
	if renamed {
		// Rename is the visibility boundary. Even if the parent-directory fsync
		// fails, retaining the new in-memory snapshot prevents a later mutation
		// from overwriting disk with stale state. A retry is safely idempotent.
		s.snap = next
	}
	if err != nil {
		return errWebStoreCorrupt
	}
	return nil
}

// ---------------------------------------------------------------------------
// Publications (implements WebDemoPublicationStore)
// ---------------------------------------------------------------------------

// webPublicationRecordFromCandidate validates the candidate and extracts the
// immutable summary fields from its manifest. The manifest was already fully
// validated by the publisher; this re-check keeps the store self-defending.
func (s *WebStateStore) webPublicationRecordFromCandidate(candidate WebStoredDemo) (*WebPublicationRecord, error) {
	if !webDemoIDPattern.MatchString(candidate.DemoID) || !validWebDigest(candidate.BundleDigest) {
		return nil, errWebStoreInvalid
	}
	if len(candidate.ManifestJSON) == 0 || len(candidate.ManifestJSON) > WebMaxPublicationBytes {
		return nil, errWebStoreInvalid
	}
	manifest, err := webDecodeAndValidatePublishedManifest(candidate.ManifestJSON)
	if err != nil {
		return nil, errWebStoreInvalid
	}
	if manifest.DemoID != candidate.DemoID || manifest.BundleDigest != candidate.BundleDigest {
		return nil, errWebStoreInvalid
	}
	bodyDigest := webBodySHA256(candidate.ManifestJSON)
	return &WebPublicationRecord{
		DemoID:         candidate.DemoID,
		BundleDigest:   candidate.BundleDigest,
		Title:          manifest.Title,
		SourceRunID:    manifest.SourceRunID,
		PublishedAt:    manifest.PublishedAt,
		ManifestPath:   s.publicationRelativePath(bodyDigest),
		ManifestSHA256: bodyDigest,
	}, nil
}

func webBodySHA256(body []byte) string {
	digest := sha256.Sum256(body)
	return "sha256:" + hex.EncodeToString(digest[:])
}

func webDecodeAndValidatePublishedManifest(raw []byte) (DemoManifest, error) {
	if len(raw) == 0 || len(raw) > WebMaxPublicationBytes {
		return DemoManifest{}, errWebStoreInvalid
	}
	if !webJSONHasUniqueObjectNames(raw) {
		return DemoManifest{}, errWebStoreInvalid
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var manifest DemoManifest
	if err := decoder.Decode(&manifest); err != nil {
		return DemoManifest{}, errWebStoreInvalid
	}
	if err := decoder.Decode(new(struct{})); !errors.Is(err, io.EOF) {
		return DemoManifest{}, errWebStoreInvalid
	}
	if err := ValidateDemoManifestForPublication(manifest); err != nil {
		return DemoManifest{}, errWebStoreInvalid
	}
	return manifest, nil
}

// webJSONHasUniqueObjectNames rejects duplicate JSON member names at every
// nesting level. encoding/json otherwise accepts the last duplicate, which is
// unsafe for immutable signed/content-addressed documents interpreted by
// multiple implementations.
func webJSONHasUniqueObjectNames(raw []byte) bool {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	var consumeValue func() bool
	consumeValue = func() bool {
		token, err := decoder.Token()
		if err != nil {
			return false
		}
		delimiter, ok := token.(json.Delim)
		if !ok {
			return true
		}
		switch delimiter {
		case '{':
			seen := make(map[string]struct{})
			for decoder.More() {
				nameToken, err := decoder.Token()
				if err != nil {
					return false
				}
				name, ok := nameToken.(string)
				if !ok {
					return false
				}
				if _, duplicate := seen[name]; duplicate {
					return false
				}
				seen[name] = struct{}{}
				if !consumeValue() {
					return false
				}
			}
			closing, err := decoder.Token()
			return err == nil && closing == json.Delim('}')
		case '[':
			for decoder.More() {
				if !consumeValue() {
					return false
				}
			}
			closing, err := decoder.Token()
			return err == nil && closing == json.Delim(']')
		default:
			return false
		}
	}
	if !consumeValue() {
		return false
	}
	_, err := decoder.Token()
	return errors.Is(err, io.EOF)
}

func (s *WebStateStore) publicationRelativePath(bodyDigest string) string {
	return filepath.Join(s.bundleRel, strings.TrimPrefix(bodyDigest, "sha256:")+".json")
}

func (s *WebStateStore) publicationAbsolutePath(record *WebPublicationRecord) (string, bool) {
	expected := s.publicationRelativePath(record.ManifestSHA256)
	if record.ManifestPath != expected || filepath.Clean(record.ManifestPath) != record.ManifestPath {
		return "", false
	}
	abs := filepath.Join(s.dir, record.ManifestPath)
	rel, err := filepath.Rel(s.bundleDir, abs)
	if err != nil || rel == "." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
		return "", false
	}
	return abs, true
}

func (s *WebStateStore) readAndValidatePublication(record *WebPublicationRecord) ([]byte, error) {
	if s.remote != nil {
		expected := s.publicationRelativePath(record.ManifestSHA256)
		if record.ManifestPath != expected || filepath.Clean(record.ManifestPath) != record.ManifestPath {
			return nil, errWebStoreCorrupt
		}
		ctx, cancel := gcsOperationContext()
		defer cancel()
		body, _, err := s.remote.read(ctx, filepath.ToSlash(record.ManifestPath), WebMaxPublicationBytes)
		if err != nil || len(body) == 0 || webBodySHA256(body) != record.ManifestSHA256 {
			return nil, errWebStoreCorrupt
		}
		manifest, err := webDecodeAndValidatePublishedManifest(body)
		if err != nil || manifest.DemoID != record.DemoID || manifest.BundleDigest != record.BundleDigest ||
			manifest.Title != record.Title || manifest.SourceRunID != record.SourceRunID || manifest.PublishedAt != record.PublishedAt {
			return nil, errWebStoreCorrupt
		}
		return body, nil
	}
	path, ok := s.publicationAbsolutePath(record)
	if !ok {
		return nil, errWebStoreCorrupt
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 || info.Size() <= 0 || info.Size() > WebMaxPublicationBytes {
		return nil, errWebStoreCorrupt
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, errWebStoreCorrupt
	}
	body, readErr := io.ReadAll(io.LimitReader(file, WebMaxPublicationBytes+1))
	closeErr := file.Close()
	if readErr != nil || closeErr != nil || len(body) == 0 || len(body) > WebMaxPublicationBytes || webBodySHA256(body) != record.ManifestSHA256 {
		return nil, errWebStoreCorrupt
	}
	manifest, err := webDecodeAndValidatePublishedManifest(body)
	if err != nil || manifest.DemoID != record.DemoID || manifest.BundleDigest != record.BundleDigest ||
		manifest.Title != record.Title || manifest.SourceRunID != record.SourceRunID || manifest.PublishedAt != record.PublishedAt {
		return nil, errWebStoreCorrupt
	}
	return body, nil
}

func (s *WebStateStore) validatePublicationBodies(snap *webSnapshot) error {
	for _, record := range snap.Publications {
		if _, err := s.readAndValidatePublication(record); err != nil {
			return webCorrupt("publication body failed integrity validation")
		}
	}
	return nil
}

// ensurePublicationBody writes an immutable content-addressed body. A hard
// link is used as the create-only visibility boundary, so a crash can leave at
// most an unindexed, valid orphan; it can never replace a published body.
func (s *WebStateStore) ensurePublicationBody(record *WebPublicationRecord, body []byte) error {
	if s.remote != nil {
		expected := s.publicationRelativePath(record.ManifestSHA256)
		if record.ManifestPath != expected || filepath.Clean(record.ManifestPath) != record.ManifestPath {
			return errWebStoreInvalid
		}
		ctx, cancel := gcsOperationContext()
		defer cancel()
		_, err := s.remote.write(ctx, filepath.ToSlash(record.ManifestPath), body, 0, true)
		if err == nil {
			return nil
		}
		if !errors.Is(err, errGCSConflict) {
			return errWebStoreCorrupt
		}
		existing, readErr := s.readAndValidatePublication(record)
		if readErr == nil && bytes.Equal(existing, body) {
			return nil
		}
		return errWebStoreConflict
	}
	path, ok := s.publicationAbsolutePath(record)
	if !ok {
		return errWebStoreInvalid
	}
	if existing, err := s.readAndValidatePublication(record); err == nil {
		if !bytes.Equal(existing, body) {
			return errWebStoreConflict
		}
		return nil
	} else if _, statErr := os.Lstat(path); statErr == nil {
		return errWebStoreCorrupt
	} else if !errors.Is(statErr, os.ErrNotExist) {
		return errWebStoreCorrupt
	}

	tmp, err := os.CreateTemp(s.bundleDir, ".manifest-*.tmp")
	if err != nil {
		return errWebStoreCorrupt
	}
	tmpPath := tmp.Name()
	defer os.Remove(tmpPath)
	if err := tmp.Chmod(0o600); err != nil {
		_ = tmp.Close()
		return errWebStoreCorrupt
	}
	if _, err := tmp.Write(body); err != nil {
		_ = tmp.Close()
		return errWebStoreCorrupt
	}
	if err := tmp.Sync(); err != nil {
		_ = tmp.Close()
		return errWebStoreCorrupt
	}
	if err := tmp.Close(); err != nil {
		return errWebStoreCorrupt
	}
	if err := os.Link(tmpPath, path); err != nil {
		if errors.Is(err, os.ErrExist) {
			existing, readErr := s.readAndValidatePublication(record)
			if readErr == nil && bytes.Equal(existing, body) {
				return nil
			}
		}
		return errWebStoreCorrupt
	}
	if err := s.syncDirectory(s.bundleDir); err != nil {
		return errWebStoreCorrupt
	}
	return nil
}

// CreateOrGetPublishedDemo atomically creates a publication indexed by both
// demoId and bundleDigest, or returns the existing immutable value for the
// demoId. It never overwrites and never leaves the two indexes divergent: a
// bundle digest already bound to a different demoId is refused outright.
func (s *WebStateStore) CreateOrGetPublishedDemo(_ context.Context, candidate WebStoredDemo) (WebStoredDemo, bool, error) {
	record, err := s.webPublicationRecordFromCandidate(candidate)
	if err != nil {
		return WebStoredDemo{}, false, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()

	for _, existing := range s.snap.Publications {
		if existing.DemoID == record.DemoID {
			body, readErr := s.readAndValidatePublication(existing)
			if readErr != nil {
				return WebStoredDemo{}, false, errWebStoreCorrupt
			}
			return existing.storedDemo(body), false, nil
		}
		if existing.BundleDigest == record.BundleDigest {
			return WebStoredDemo{}, false, errWebStoreConflict
		}
	}
	if len(s.snap.Publications) >= webMaxStoredPublications {
		return WebStoredDemo{}, false, errWebStoreConflict
	}
	if err := s.ensurePublicationBody(record, candidate.ManifestJSON); err != nil {
		return WebStoredDemo{}, false, err
	}
	next, err := s.cloneLocked()
	if err != nil {
		return WebStoredDemo{}, false, err
	}
	next.Publications = append(next.Publications, record)
	if err := s.commitLocked(next); err != nil {
		return WebStoredDemo{}, false, err
	}
	return record.storedDemo(candidate.ManifestJSON), true, nil
}

// PublishedDemoByID returns a copy of one publication.
func (s *WebStateStore) PublishedDemoByID(demoID string) (WebPublicationRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.Publications {
		if record.DemoID == demoID {
			body, err := s.readAndValidatePublication(record)
			if err != nil {
				return WebPublicationRecord{}, false
			}
			out := *record
			out.ManifestJSON = append([]byte(nil), body...)
			return out, true
		}
	}
	return WebPublicationRecord{}, false
}

// PublishedDemoByDigest resolves the content-addressed index.
func (s *WebStateStore) PublishedDemoByDigest(bundleDigest string) (WebPublicationRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.Publications {
		if record.BundleDigest == bundleDigest {
			body, err := s.readAndValidatePublication(record)
			if err != nil {
				return WebPublicationRecord{}, false
			}
			out := *record
			out.ManifestJSON = append([]byte(nil), body...)
			return out, true
		}
	}
	return WebPublicationRecord{}, false
}

// PublishedDemoSummaries lists all publications, newest first.
func (s *WebStateStore) PublishedDemoSummaries() []WebDemoSummary {
	s.mu.Lock()
	defer s.mu.Unlock()
	summaries := make([]WebDemoSummary, 0, len(s.snap.Publications))
	for _, record := range s.snap.Publications {
		summaries = append(summaries, WebDemoSummary{
			SchemaVersion: WebSchemaVersion,
			DemoID:        record.DemoID,
			Title:         record.Title,
			SourceRunID:   record.SourceRunID,
			PublishedAt:   record.PublishedAt,
			BundleDigest:  record.BundleDigest,
		})
	}
	sort.Slice(summaries, func(i, j int) bool {
		if summaries[i].PublishedAt != summaries[j].PublishedAt {
			return summaries[i].PublishedAt > summaries[j].PublishedAt
		}
		return summaries[i].DemoID < summaries[j].DemoID
	})
	if len(summaries) > webMaxStoredPublications {
		summaries = summaries[:webMaxStoredPublications]
	}
	return summaries
}

// ---------------------------------------------------------------------------
// Run ownership
// ---------------------------------------------------------------------------

// PutRunOwnership durably records the owner of a newly created run. It is
// create-only: an existing binding is never replaced.
func (s *WebStateStore) PutRunOwnership(record WebRunOwnershipRecord) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	ownerCount := 0
	for _, existing := range s.snap.RunOwnerships {
		if existing.RunID == record.RunID {
			return errWebStoreConflict
		}
		if existing.OwnerUID == record.OwnerUID {
			ownerCount++
		}
	}
	if len(s.snap.RunOwnerships) >= webMaxStoredOwnerships || ownerCount >= webMaxOwnerOwnerships {
		return errWebStoreConflict
	}
	next, err := s.cloneLocked()
	if err != nil {
		return err
	}
	copied := record
	next.RunOwnerships = append(next.RunOwnerships, &copied)
	return s.commitLocked(next)
}

// RunOwnership returns a copy of one ownership binding.
func (s *WebStateStore) RunOwnership(runID string) (WebRunOwnershipRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.RunOwnerships {
		if record.RunID == runID {
			return *record, true
		}
	}
	return WebRunOwnershipRecord{}, false
}

// RunOwnershipsForOwner lists the caller's own runs, oldest first.
func (s *WebStateStore) RunOwnershipsForOwner(ownerUID string) []WebRunOwnershipRecord {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]WebRunOwnershipRecord, 0)
	for _, record := range s.snap.RunOwnerships {
		if record.OwnerUID == ownerUID {
			out = append(out, *record)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt != out[j].CreatedAt {
			return out[i].CreatedAt < out[j].CreatedAt
		}
		return out[i].RunID < out[j].RunID
	})
	return out
}

// ---------------------------------------------------------------------------
// Trusted publication records
// ---------------------------------------------------------------------------

// putTrustedPublicationRecord upserts the owner-controlled server-side record
// that gates publication of one run. It is written by trusted wiring (never
// from a browser request body) and rebinds only for the same owner.
func (s *WebStateStore) putTrustedPublicationRecord(ownerUID string, record WebTrustedRunPublicationRecord) error {
	if !webValidSubject(ownerUID) || !webRunIDPattern.MatchString(record.SourceRunID) {
		return errWebStoreInvalid
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	next, err := s.cloneLocked()
	if err != nil {
		return err
	}
	stored := &webTrustedPublicationRecord{
		OwnerUID:              ownerUID,
		SourceRunID:           record.SourceRunID,
		DataClass:             record.DataClass,
		State:                 record.State,
		FullyReconciled:       record.FullyReconciled,
		OwnerApprovalVerified: record.OwnerApprovalVerified,
		PortfolioPlanDigest:   record.PortfolioPlanDigest,
	}
	replaced := false
	ownerCount := 0
	for i, existing := range next.TrustedPublications {
		if existing.OwnerUID == ownerUID {
			ownerCount++
		}
		if existing.SourceRunID == record.SourceRunID {
			if existing.OwnerUID != ownerUID {
				return errWebStoreConflict
			}
			next.TrustedPublications[i] = stored
			replaced = true
			break
		}
	}
	if !replaced {
		if len(next.TrustedPublications) >= webMaxStoredTrusted || ownerCount >= webMaxOwnerTrusted {
			return errWebStoreConflict
		}
		next.TrustedPublications = append(next.TrustedPublications, stored)
	}
	return s.commitLocked(next)
}

// TrustedPublicationRecord returns the record only to its owner.
func (s *WebStateStore) TrustedPublicationRecord(ownerUID, sourceRunID string) (WebTrustedRunPublicationRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.TrustedPublications {
		if record.SourceRunID == sourceRunID && record.OwnerUID == ownerUID {
			return WebTrustedRunPublicationRecord{
				SourceRunID:           record.SourceRunID,
				DataClass:             record.DataClass,
				State:                 record.State,
				FullyReconciled:       record.FullyReconciled,
				OwnerApprovalVerified: record.OwnerApprovalVerified,
				PortfolioPlanDigest:   record.PortfolioPlanDigest,
			}, true
		}
	}
	return WebTrustedRunPublicationRecord{}, false
}

// ---------------------------------------------------------------------------
// Cloud setups
// ---------------------------------------------------------------------------

// PutCloudSetup durably records a new pending setup. Create-only.
func (s *WebStateStore) PutCloudSetup(record WebCloudSetupRecord) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	ownerCount := 0
	for _, existing := range s.snap.CloudSetups {
		if existing.SetupID == record.SetupID {
			return errWebStoreConflict
		}
		if existing.OwnerUID == record.OwnerUID {
			ownerCount++
		}
	}
	if len(s.snap.CloudSetups) >= webMaxStoredSetups || ownerCount >= webMaxOwnerSetups {
		return errWebStoreConflict
	}
	next, err := s.cloneLocked()
	if err != nil {
		return err
	}
	copied := record
	copied.MissingCapabilities = append([]string(nil), record.MissingCapabilities...)
	next.CloudSetups = append(next.CloudSetups, &copied)
	return s.commitLocked(next)
}

// CloudSetup returns a copy of one setup, scoped to its owner. A foreign
// setup is indistinguishable from a missing one.
func (s *WebStateStore) CloudSetup(ownerUID, setupID string) (WebCloudSetupRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.CloudSetups {
		if record.SetupID == setupID && record.OwnerUID == ownerUID {
			out := *record
			out.MissingCapabilities = append([]string(nil), record.MissingCapabilities...)
			return out, true
		}
	}
	return WebCloudSetupRecord{}, false
}

// CloudSetupsForOwner lists the caller's own setups.
func (s *WebStateStore) CloudSetupsForOwner(ownerUID string) []WebCloudSetupRecord {
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]WebCloudSetupRecord, 0)
	for _, record := range s.snap.CloudSetups {
		if record.OwnerUID == ownerUID {
			copied := *record
			copied.MissingCapabilities = append([]string(nil), record.MissingCapabilities...)
			out = append(out, copied)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].CreatedAt != out[j].CreatedAt {
			return out[i].CreatedAt < out[j].CreatedAt
		}
		return out[i].SetupID < out[j].SetupID
	})
	return out
}

// RecordCloudVerification applies the outcome of one verify attempt. An
// empty missing set marks the setup verified; a non-empty set records the
// gaps honestly, degrading a previously verified setup rather than
// preserving a claim that is no longer true.
func (s *WebStateStore) RecordCloudVerification(ownerUID, setupID, attemptedAt string, missing []string) (WebCloudSetupRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	next, err := s.cloneLocked()
	if err != nil {
		return WebCloudSetupRecord{}, err
	}
	var target *WebCloudSetupRecord
	for _, record := range next.CloudSetups {
		if record.SetupID == setupID && record.OwnerUID == ownerUID {
			target = record
			break
		}
	}
	if target == nil {
		return WebCloudSetupRecord{}, errWebStoreNotFound
	}
	if target.Status != webCloudSetupVerifying {
		return WebCloudSetupRecord{}, errWebStoreConflict
	}
	if len(missing) == 0 {
		target.Status = webCloudSetupVerified
		target.VerifiedAt = attemptedAt
		target.MissingCapabilities = nil
	} else {
		target.Status = webCloudSetupDegraded
		target.MissingCapabilities = append([]string(nil), missing...)
	}
	if err := s.commitLocked(next); err != nil {
		return WebCloudSetupRecord{}, err
	}
	out := *target
	out.MissingCapabilities = append([]string(nil), target.MissingCapabilities...)
	return out, nil
}

func (s *WebStateStore) BeginCloudVerification(ownerUID, setupID, receiptSHA256, attemptedAt string) (WebCloudSetupRecord, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	next, err := s.cloneLocked()
	if err != nil {
		return WebCloudSetupRecord{}, err
	}
	var target *WebCloudSetupRecord
	for _, record := range next.CloudSetups {
		if record.SetupID == setupID && record.OwnerUID == ownerUID {
			target = record
			break
		}
	}
	if target == nil {
		return WebCloudSetupRecord{}, errWebStoreNotFound
	}
	if target.Status != webCloudSetupPending {
		return WebCloudSetupRecord{}, errWebStoreReceipt
	}
	attempt, okAttempt := cpParseStamp(attemptedAt)
	expiry, okExpiry := cpParseStamp(target.ExpiresAt)
	if !okAttempt || !okExpiry || !attempt.Before(expiry) {
		return WebCloudSetupRecord{}, errWebStoreExpired
	}
	if subtle.ConstantTimeCompare([]byte(receiptSHA256), []byte(target.ReceiptSHA256)) != 1 {
		return WebCloudSetupRecord{}, errWebStoreReceipt
	}
	target.Status = webCloudSetupVerifying
	target.VerifiedAt = attemptedAt
	target.MissingCapabilities = nil
	if err := s.commitLocked(next); err != nil {
		return WebCloudSetupRecord{}, err
	}
	out := *target
	return out, nil
}

// ---------------------------------------------------------------------------
// Driver research
// ---------------------------------------------------------------------------

// CreateDriverResearch durably records a new queued research task.
func (s *WebStateStore) CreateDriverResearch(record WebDriverResearchRecord) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	ownerCount := 0
	for _, existing := range s.snap.DriverResearch {
		if existing.ResearchID == record.ResearchID {
			return errWebStoreConflict
		}
		if existing.OwnerUID == record.OwnerUID {
			ownerCount++
		}
	}
	if len(s.snap.DriverResearch) >= webMaxStoredResearch || ownerCount >= webMaxOwnerResearch {
		return errWebStoreConflict
	}
	next, err := s.cloneLocked()
	if err != nil {
		return err
	}
	copied := record.clone()
	next.DriverResearch = append(next.DriverResearch, &copied)
	return s.commitLocked(next)
}

// DriverResearch returns a copy of one task, scoped to its owner.
func (s *WebStateStore) DriverResearch(ownerUID, researchID string) (WebDriverResearchRecord, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, record := range s.snap.DriverResearch {
		if record.ResearchID == researchID && record.OwnerUID == ownerUID {
			return record.clone(), true
		}
	}
	return WebDriverResearchRecord{}, false
}

func (s *WebStateStore) updateResearch(researchID string, apply func(record *WebDriverResearchRecord) error) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	next, err := s.cloneLocked()
	if err != nil {
		return err
	}
	var target *WebDriverResearchRecord
	for _, record := range next.DriverResearch {
		if record.ResearchID == researchID {
			target = record
			break
		}
	}
	if target == nil {
		return errWebStoreNotFound
	}
	if err := apply(target); err != nil {
		return err
	}
	return s.commitLocked(next)
}

// SetDriverResearchRunning transitions queued work to running.
func (s *WebStateStore) SetDriverResearchRunning(researchID, updatedAt string) error {
	return s.updateResearch(researchID, func(record *WebDriverResearchRecord) error {
		if record.Status != webResearchQueued {
			return errWebStoreConflict
		}
		record.Status = webResearchRunning
		record.UpdatedAt = updatedAt
		return nil
	})
}

// CompleteDriverResearch records a validated result exactly once.
func (s *WebStateStore) CompleteDriverResearch(researchID string, result WebDriverResearchResponse, updatedAt string) error {
	return s.updateResearch(researchID, func(record *WebDriverResearchRecord) error {
		if record.Status != webResearchQueued && record.Status != webResearchRunning {
			return errWebStoreConflict
		}
		copied := result
		copied.Candidates = append([]WebDriverCandidate(nil), result.Candidates...)
		record.Status = webResearchCompleted
		record.Result = &copied
		record.FailureCode = ""
		record.UpdatedAt = updatedAt
		return nil
	})
}

// FailDriverResearch records a closed failure code exactly once.
func (s *WebStateStore) FailDriverResearch(researchID, failureCode, updatedAt string) error {
	return s.updateResearch(researchID, func(record *WebDriverResearchRecord) error {
		if record.Status != webResearchQueued && record.Status != webResearchRunning {
			return errWebStoreConflict
		}
		record.Status = webResearchFailed
		record.FailureCode = failureCode
		record.Result = nil
		record.UpdatedAt = updatedAt
		return nil
	})
}

// PutDriverApproval records the single immutable approval for one research
// task. Create-only.
func (s *WebStateStore) PutDriverApproval(researchID string, approval WebDriverApprovalResponse) error {
	return s.updateResearch(researchID, func(record *WebDriverResearchRecord) error {
		if record.Status != webResearchCompleted || record.Approval != nil {
			return errWebStoreConflict
		}
		copied := approval
		record.Approval = &copied
		record.UpdatedAt = approval.ApprovedAt
		return nil
	})
}

// ---------------------------------------------------------------------------
// Snapshot validation
// ---------------------------------------------------------------------------

func webValidCapabilityList(caps []string) bool {
	if len(caps) > webMaxMissingCaps {
		return false
	}
	for _, capability := range caps {
		if !webSafeBoundedText(capability, 200) {
			return false
		}
	}
	return true
}

func webValidDriverCandidate(candidate WebDriverCandidate, seen map[string]bool) bool {
	if !webCandidateIDPattern.MatchString(candidate.CandidateID) || seen[candidate.CandidateID] {
		return false
	}
	seen[candidate.CandidateID] = true
	if !webSafeBoundedText(candidate.Coordinates, 300) || !webSafeBoundedText(candidate.Version, 120) {
		return false
	}
	if !webValidHTTPSURL(candidate.OfficialSource, 2000) {
		return false
	}
	if !webSafeBoundedText(candidate.Compatibility, 1000) || !webSafeBoundedText(candidate.License, 200) {
		return false
	}
	switch candidate.Redistribution {
	case "allowed", "restricted", "unknown":
	default:
		return false
	}
	if candidate.Confidence < 0 || candidate.Confidence > 1 {
		return false
	}
	if len(candidate.Caveats) > 50 {
		return false
	}
	for _, caveat := range candidate.Caveats {
		if !webSafeBoundedText(caveat, 500) {
			return false
		}
	}
	return true
}

func webValidResearchResult(result WebDriverResearchResponse, researchID string) bool {
	if result.SchemaVersion != WebSchemaVersion || result.ResearchID != researchID {
		return false
	}
	if !webGeminiModelPattern.MatchString(result.Model) || !webProjectIDPattern.MatchString(result.ProjectID) {
		return false
	}
	if _, ok := cpParseStamp(result.CreatedAt); !ok {
		return false
	}
	if len(result.Candidates) < 1 || len(result.Candidates) > 50 {
		return false
	}
	seen := make(map[string]bool, len(result.Candidates))
	for _, candidate := range result.Candidates {
		if !webValidDriverCandidate(candidate, seen) {
			return false
		}
	}
	return validWebDigest(result.EvidenceDigest)
}

func webValidResearchRequest(request WebDriverResearchRequest) bool {
	if request.SchemaVersion != WebSchemaVersion || !webProjectIDPattern.MatchString(request.ProjectID) {
		return false
	}
	for _, field := range []string{request.DatabaseFamily, request.DatabaseVersion, request.ApplicationLayer, request.JavaRuntime} {
		if !webSafeBoundedText(field, 120) {
			return false
		}
	}
	switch request.ConnectivityMode {
	case "tailscale", "private_service_connect", "vpn":
	default:
		return false
	}
	if request.OfficialRepository != "" && !webValidHTTPSURL(request.OfficialRepository, 2000) {
		return false
	}
	return true
}

func webValidateStoreSnapshot(snap *webSnapshot) error {
	if snap == nil {
		return webCorrupt("missing snapshot")
	}
	if snap.SnapshotVersion != webSnapshotVersion {
		return webCorrupt("unsupported snapshot version")
	}
	if snap.SchemaVersion != WebSchemaVersion {
		return webCorrupt("unsupported contract version")
	}

	if len(snap.Publications) > webMaxStoredPublications {
		return webCorrupt("publication capacity exceeded")
	}
	demoIDs := make(map[string]bool, len(snap.Publications))
	digests := make(map[string]bool, len(snap.Publications))
	for _, record := range snap.Publications {
		if record == nil {
			return webCorrupt("nil publication")
		}
		if !webDemoIDPattern.MatchString(record.DemoID) || !validWebDigest(record.BundleDigest) {
			return webCorrupt("malformed publication identity")
		}
		if demoIDs[record.DemoID] || digests[record.BundleDigest] {
			return webCorrupt("duplicate publication index")
		}
		demoIDs[record.DemoID] = true
		digests[record.BundleDigest] = true
		if !webSafeBoundedText(record.Title, 120) || !webRunIDPattern.MatchString(record.SourceRunID) {
			return webCorrupt("malformed publication summary")
		}
		if _, ok := cpParseStamp(record.PublishedAt); !ok {
			return webCorrupt("malformed publication timestamp")
		}
		if !validWebDigest(record.ManifestSHA256) || record.ManifestPath == "" || filepath.IsAbs(record.ManifestPath) ||
			filepath.Clean(record.ManifestPath) != record.ManifestPath ||
			filepath.Base(record.ManifestPath) != strings.TrimPrefix(record.ManifestSHA256, "sha256:")+".json" ||
			len(strings.Split(record.ManifestPath, string(filepath.Separator))) != 2 {
			return webCorrupt("malformed publication body reference")
		}
	}

	if len(snap.RunOwnerships) > webMaxStoredOwnerships {
		return webCorrupt("ownership capacity exceeded")
	}
	runIDs := make(map[string]bool, len(snap.RunOwnerships))
	ownershipsByOwner := make(map[string]int)
	for _, record := range snap.RunOwnerships {
		if record == nil {
			return webCorrupt("nil ownership")
		}
		if !webRunIDPattern.MatchString(record.RunID) || runIDs[record.RunID] {
			return webCorrupt("malformed or duplicate ownership run id")
		}
		runIDs[record.RunID] = true
		if !webValidSubject(record.OwnerUID) {
			return webCorrupt("malformed ownership owner")
		}
		ownershipsByOwner[record.OwnerUID]++
		if ownershipsByOwner[record.OwnerUID] > webMaxOwnerOwnerships {
			return webCorrupt("per-owner ownership capacity exceeded")
		}
		if !webSafeBoundedText(record.PortfolioName, 120) {
			return webCorrupt("malformed ownership portfolio name")
		}
		if !webValidSubject(record.Owner.Subject) || record.Owner.Subject != record.OwnerUID ||
			!webSafeBoundedText(record.Owner.DisplayName, 200) || !webValidEmail(record.Owner.Email) {
			return webCorrupt("malformed ownership identity")
		}
		if record.Owner.PictureURL != "" && !webValidHTTPSURL(record.Owner.PictureURL, 2000) {
			return webCorrupt("malformed ownership picture")
		}
		if _, ok := cpParseStamp(record.CreatedAt); !ok {
			return webCorrupt("malformed ownership timestamp")
		}
	}
	if err := webValidateTerminalSnapshot(snap.TerminalFrames, runIDs); err != nil {
		return err
	}

	if len(snap.TrustedPublications) > webMaxStoredTrusted {
		return webCorrupt("trusted publication capacity exceeded")
	}
	trustedRuns := make(map[string]bool, len(snap.TrustedPublications))
	trustedByOwner := make(map[string]int)
	for _, record := range snap.TrustedPublications {
		if record == nil {
			return webCorrupt("nil trusted record")
		}
		if !webRunIDPattern.MatchString(record.SourceRunID) || trustedRuns[record.SourceRunID] {
			return webCorrupt("malformed or duplicate trusted record")
		}
		trustedRuns[record.SourceRunID] = true
		if !webValidSubject(record.OwnerUID) {
			return webCorrupt("malformed trusted record owner")
		}
		trustedByOwner[record.OwnerUID]++
		if trustedByOwner[record.OwnerUID] > webMaxOwnerTrusted {
			return webCorrupt("per-owner trusted publication capacity exceeded")
		}
		if record.DataClass != DataClassSyntheticDemo && record.DataClass != DataClassPrivate {
			return webCorrupt("unknown trusted record class")
		}
		if !cpIsKnownState(ControlPlaneState(record.State)) {
			return webCorrupt("unknown trusted record state")
		}
		if !validWebDigest(record.PortfolioPlanDigest) {
			return webCorrupt("malformed trusted record digest")
		}
	}

	if len(snap.CloudSetups) > webMaxStoredSetups {
		return webCorrupt("setup capacity exceeded")
	}
	setupIDs := make(map[string]bool, len(snap.CloudSetups))
	setupsByOwner := make(map[string]int)
	for _, record := range snap.CloudSetups {
		if record == nil {
			return webCorrupt("nil setup")
		}
		if !webSetupIDPattern.MatchString(record.SetupID) || setupIDs[record.SetupID] {
			return webCorrupt("malformed or duplicate setup id")
		}
		setupIDs[record.SetupID] = true
		if !webValidSubject(record.OwnerUID) {
			return webCorrupt("malformed setup owner")
		}
		setupsByOwner[record.OwnerUID]++
		if setupsByOwner[record.OwnerUID] > webMaxOwnerSetups {
			return webCorrupt("per-owner setup capacity exceeded")
		}
		if !webProjectIDPattern.MatchString(record.ProjectID) ||
			!webRegionPattern.MatchString(record.Region) ||
			!webDatasetPrefixPattern.MatchString(record.DatasetPrefix) {
			return webCorrupt("malformed setup target")
		}
		setupSuffix := strings.TrimPrefix(record.SetupID, "setup_")
		if len(setupSuffix) < 12 {
			return webCorrupt("malformed setup resource binding")
		}
		expectedPrefix := "ztm-" + setupSuffix[:12]
		if record.ResourcePrefix != expectedPrefix || record.ServiceAccountName != expectedPrefix ||
			record.RepositoryName != expectedPrefix+"-drivers" || record.BucketName != record.ProjectID+"-"+expectedPrefix {
			return webCorrupt("malformed setup resource binding")
		}
		if !validWebDigest(record.CommandDigest) || !webReceiptHashPattern.MatchString(record.ReceiptSHA256) {
			return webCorrupt("malformed setup binding")
		}
		if _, ok := cpParseStamp(record.CreatedAt); !ok {
			return webCorrupt("malformed setup created timestamp")
		}
		if _, ok := cpParseStamp(record.ExpiresAt); !ok {
			return webCorrupt("malformed setup expiry timestamp")
		}
		switch record.Status {
		case webCloudSetupPending:
			if record.VerifiedAt != "" {
				return webCorrupt("pending setup carries a verification timestamp")
			}
		case webCloudSetupVerifying:
			if _, ok := cpParseStamp(record.VerifiedAt); !ok {
				return webCorrupt("verifying setup has no claim timestamp")
			}
		case webCloudSetupVerified, webCloudSetupDegraded:
			if _, ok := cpParseStamp(record.VerifiedAt); !ok {
				return webCorrupt("verified setup without a verification timestamp")
			}
			if record.Status == webCloudSetupVerified && len(record.MissingCapabilities) != 0 {
				return webCorrupt("verified setup reports missing capabilities")
			}
		default:
			return webCorrupt("unknown setup status")
		}
		if !webValidCapabilityList(record.MissingCapabilities) {
			return webCorrupt("malformed setup capability list")
		}
	}

	if len(snap.DriverResearch) > webMaxStoredResearch {
		return webCorrupt("research capacity exceeded")
	}
	researchIDs := make(map[string]bool, len(snap.DriverResearch))
	researchByOwner := make(map[string]int)
	for _, record := range snap.DriverResearch {
		if record == nil {
			return webCorrupt("nil research")
		}
		if !webResearchIDPattern.MatchString(record.ResearchID) || researchIDs[record.ResearchID] {
			return webCorrupt("malformed or duplicate research id")
		}
		researchIDs[record.ResearchID] = true
		if !webValidSubject(record.OwnerUID) {
			return webCorrupt("malformed research owner")
		}
		researchByOwner[record.OwnerUID]++
		if researchByOwner[record.OwnerUID] > webMaxOwnerResearch {
			return webCorrupt("per-owner research capacity exceeded")
		}
		if !webValidResearchRequest(record.Request) {
			return webCorrupt("malformed research request")
		}
		if _, ok := cpParseStamp(record.CreatedAt); !ok {
			return webCorrupt("malformed research created timestamp")
		}
		if _, ok := cpParseStamp(record.UpdatedAt); !ok {
			return webCorrupt("malformed research updated timestamp")
		}
		switch record.Status {
		case webResearchQueued, webResearchRunning:
			if record.Result != nil || record.FailureCode != "" || record.Approval != nil {
				return webCorrupt("pending research carries an outcome")
			}
		case webResearchCompleted:
			if record.Result == nil || record.FailureCode != "" {
				return webCorrupt("completed research without a result")
			}
			if !webValidResearchResult(*record.Result, record.ResearchID) {
				return webCorrupt("completed research carries an invalid result")
			}
		case webResearchFailed:
			if record.Result != nil || record.Approval != nil || !cpFailureCodeRe.MatchString(record.FailureCode) {
				return webCorrupt("failed research without a closed failure code")
			}
		default:
			return webCorrupt("unknown research status")
		}
		if record.Approval != nil {
			approval := record.Approval
			if record.Status != webResearchCompleted || record.Result == nil {
				return webCorrupt("approval on unfinished research")
			}
			if approval.SchemaVersion != WebSchemaVersion || approval.ResearchID != record.ResearchID {
				return webCorrupt("approval does not bind its research")
			}
			found := false
			for _, candidate := range record.Result.Candidates {
				if candidate.CandidateID == approval.CandidateID {
					found = true
					break
				}
			}
			if !found {
				return webCorrupt("approval names an unknown candidate")
			}
			switch approval.Status {
			case "pending_upload", "retrieving":
				if approval.ArtifactFingerprint != "" {
					return webCorrupt("unverified approval carries a fingerprint")
				}
			case "verified":
				if !validWebDigest(approval.ArtifactFingerprint) {
					return webCorrupt("verified approval without a fingerprint")
				}
			default:
				return webCorrupt("unknown approval status")
			}
			switch approval.RetrievalMode {
			case "artifact_registry_remote", "manual_vendor_upload":
			default:
				return webCorrupt("unknown approval retrieval mode")
			}
			if _, ok := cpParseStamp(approval.ApprovedAt); !ok {
				return webCorrupt("malformed approval timestamp")
			}
		}
	}
	return nil
}
