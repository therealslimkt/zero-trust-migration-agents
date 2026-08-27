package main

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"

	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
)

const (
	webArtifactRegistryScope         = "https://www.googleapis.com/auth/cloud-platform"
	webDefaultArtifactMaxBytes int64 = 128 << 20
)

var (
	webMavenCoordinatePattern = regexp.MustCompile(`^([A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*):([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$`)
	webMavenVersionPattern    = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]{0,119}$`)
	webArtifactRepoPattern    = regexp.MustCompile(`^[a-z][a-z0-9-]{2,61}[a-z0-9]$`)

	errWebArtifactConfiguration = errors.New("artifact registry: invalid configuration")
	errWebArtifactCandidate     = errors.New("artifact registry: invalid maven candidate")
	errWebArtifactResponse      = errors.New("artifact registry: unexpected artifact response")
)

// WebArtifactRegistryRemoteConfig supplies only deployment-controlled
// transport limits. The exact customer project/repository comes from a
// server-owned, verified WebCloudSetupRecord on every request.
type WebArtifactRegistryRemoteConfig struct {
	MaxArtifactBytes int64

	// TokenSource is injectable for tests. Nil obtains ADC with the Cloud
	// Platform scope; no key material is accepted by this provider.
	TokenSource oauth2.TokenSource
	HTTPClient  *http.Client
}

// WebArtifactRegistryRemote fingerprints Maven JARs proxied by one configured
// Artifact Registry remote repository. It never executes, loads, or unpacks an
// artifact; its only output is a content digest.
type WebArtifactRegistryRemote struct {
	maxBytes int64
	tokens   oauth2.TokenSource
	client   *http.Client
}

var _ WebDriverArtifactRegistry = (*WebArtifactRegistryRemote)(nil)

// NewWebArtifactRegistryRemote builds a provider that obtains bearer tokens
// from Application Default Credentials when a test token source is not given.
func NewWebArtifactRegistryRemote(ctx context.Context, cfg WebArtifactRegistryRemoteConfig) (*WebArtifactRegistryRemote, error) {
	maxBytes := cfg.MaxArtifactBytes
	if maxBytes == 0 {
		maxBytes = webDefaultArtifactMaxBytes
	}
	if maxBytes < 4 {
		return nil, errWebArtifactConfiguration
	}
	tokens := cfg.TokenSource
	if tokens == nil {
		var err error
		tokens, err = google.DefaultTokenSource(ctx, webArtifactRegistryScope)
		if err != nil {
			return nil, fmt.Errorf("artifact registry: ADC token source: %w", err)
		}
	}
	client := cfg.HTTPClient
	if client == nil {
		client = &http.Client{Timeout: 30 * time.Second}
	}
	// Clone an injected client as well: redirects are never permitted, even in
	// a caller-supplied client with a permissive redirect policy.
	cloned := *client
	if cloned.Timeout == 0 {
		cloned.Timeout = 30 * time.Second
	}
	cloned.CheckRedirect = func(_ *http.Request, _ []*http.Request) error {
		return errors.New("artifact registry: redirect rejected")
	}

	return &WebArtifactRegistryRemote{
		maxBytes: maxBytes,
		tokens:   tokens,
		client:   &cloned,
	}, nil
}

// FingerprintArtifactRegistryRemote implements WebDriverArtifactRegistry.
// Candidate.OfficialSource is intentionally not used as a request URL: the
// configured repository, validated Maven coordinates, and version solely
// determine the network destination and object path.
func (registry *WebArtifactRegistryRemote) FingerprintArtifactRegistryRemote(ctx context.Context, setup WebCloudSetupRecord, candidate WebDriverCandidate) (string, error) {
	if registry == nil || setup.Status != webCloudSetupVerified || !webArtifactSetupBindingValid(setup) {
		return "", errWebArtifactCandidate
	}
	artifactURL, err := registry.artifactURL(setup, candidate.Coordinates, candidate.Version)
	if err != nil {
		return "", err
	}
	token, err := registry.tokens.Token()
	if err != nil {
		return "", fmt.Errorf("artifact registry: ADC token: %w", err)
	}
	if token == nil || token.AccessToken == "" {
		return "", errors.New("artifact registry: empty ADC token")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, artifactURL.String(), nil)
	if err != nil {
		return "", fmt.Errorf("artifact registry: create request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+token.AccessToken)
	req.Header.Set("Accept", "application/java-archive, application/x-java-archive, application/octet-stream")
	response, err := registry.client.Do(req)
	if err != nil {
		return "", fmt.Errorf("artifact registry: request failed: %w", err)
	}
	defer response.Body.Close()
	expectedHost := setup.Region + "-maven.pkg.dev"
	if response.Request != nil && (response.Request.URL.Scheme != "https" || !strings.EqualFold(response.Request.URL.Host, expectedHost)) {
		return "", errWebArtifactResponse
	}
	if response.StatusCode != http.StatusOK || !webJarContentType(response.Header.Get("Content-Type")) || response.ContentLength > registry.maxBytes {
		return "", errWebArtifactResponse
	}

	limited := &io.LimitedReader{R: response.Body, N: registry.maxBytes + 1}
	reader := bufio.NewReader(limited)
	magic := make([]byte, 4)
	if _, err := io.ReadFull(reader, magic); err != nil || string(magic) != "PK\x03\x04" {
		return "", errWebArtifactResponse
	}
	hash := sha256.New()
	_, _ = hash.Write(magic)
	written, err := io.Copy(hash, reader)
	if err != nil || written+int64(len(magic)) > registry.maxBytes {
		return "", errWebArtifactResponse
	}
	return "sha256:" + hex.EncodeToString(hash.Sum(nil)), nil
}

func (registry *WebArtifactRegistryRemote) artifactURL(setup WebCloudSetupRecord, coordinates, version string) (*url.URL, error) {
	match := webMavenCoordinatePattern.FindStringSubmatch(coordinates)
	if len(match) != 3 || !webMavenVersionPattern.MatchString(version) || version == "." || strings.Contains(version, "..") {
		return nil, errWebArtifactCandidate
	}
	groupID, artifactID := match[1], match[2]
	if groupID == "." || strings.Contains(groupID, "..") || strings.Contains(artifactID, "..") {
		return nil, errWebArtifactCandidate
	}
	groupPath := strings.ReplaceAll(groupID, ".", "/")
	return &url.URL{
		Scheme: "https",
		Host:   setup.Region + "-maven.pkg.dev",
		Path:   "/" + setup.ProjectID + "/" + setup.RepositoryName + "/" + groupPath + "/" + artifactID + "/" + version + "/" + artifactID + "-" + version + ".jar",
	}, nil
}

func webArtifactSetupBindingValid(setup WebCloudSetupRecord) bool {
	if !webSetupIDPattern.MatchString(setup.SetupID) || !webProjectIDPattern.MatchString(setup.ProjectID) ||
		!webRegionPattern.MatchString(setup.Region) || !webArtifactRepoPattern.MatchString(setup.RepositoryName) {
		return false
	}
	suffix := strings.TrimPrefix(setup.SetupID, "setup_")
	if len(suffix) < 12 {
		return false
	}
	prefix := "ztm-" + suffix[:12]
	return setup.ResourcePrefix == prefix && setup.ServiceAccountName == prefix &&
		setup.RepositoryName == prefix+"-drivers" && setup.BucketName == setup.ProjectID+"-"+prefix
}

func webJarContentType(value string) bool {
	mediaType := strings.ToLower(strings.TrimSpace(strings.Split(value, ";")[0]))
	switch mediaType {
	case "application/java-archive", "application/x-java-archive", "application/octet-stream":
		return true
	default:
		return false
	}
}
