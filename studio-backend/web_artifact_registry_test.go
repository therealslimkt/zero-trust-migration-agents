package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"golang.org/x/oauth2"
)

type webArtifactRoundTripper func(*http.Request) (*http.Response, error)

func (fn webArtifactRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	return fn(req)
}

func webArtifactTestRegistry(t *testing.T, transport webArtifactRoundTripper, maxBytes int64) *WebArtifactRegistryRemote {
	t.Helper()
	registry, err := NewWebArtifactRegistryRemote(context.Background(), WebArtifactRegistryRemoteConfig{
		MaxArtifactBytes: maxBytes,
		TokenSource:      oauth2.StaticTokenSource(&oauth2.Token{AccessToken: "test-adc-token"}),
		HTTPClient:       &http.Client{Transport: transport},
	})
	if err != nil {
		t.Fatalf("NewWebArtifactRegistryRemote() error = %v", err)
	}
	return registry
}

func webArtifactSetup() WebCloudSetupRecord {
	return WebCloudSetupRecord{
		SetupID: "setup_1234567890abcdef12345678", ProjectID: "owner-project1", Region: "us-central1",
		ResourcePrefix: "ztm-1234567890ab", ServiceAccountName: "ztm-1234567890ab",
		RepositoryName: "ztm-1234567890ab-drivers", BucketName: "owner-project1-ztm-1234567890ab",
		Status: webCloudSetupVerified,
	}
}

func webArtifactResponse(req *http.Request, status int, contentType string, body []byte) *http.Response {
	return &http.Response{
		StatusCode:    status,
		Header:        http.Header{"Content-Type": []string{contentType}},
		Body:          io.NopCloser(bytes.NewReader(body)),
		ContentLength: int64(len(body)),
		Request:       req,
	}
}

func webArtifactCandidate() WebDriverCandidate {
	return WebDriverCandidate{Coordinates: "com.vendor:jdbc-driver", Version: "1.2.3"}
}

func TestWebArtifactRegistryRemoteFingerprintsExactConfiguredMavenPath(t *testing.T) {
	jar := []byte("PK\x03\x04minimal-jar-body")
	wantSum := sha256.Sum256(jar)
	requests := 0
	registry := webArtifactTestRegistry(t, func(req *http.Request) (*http.Response, error) {
		requests++
		if got, want := req.URL.String(), "https://us-central1-maven.pkg.dev/owner-project1/ztm-1234567890ab-drivers/com/vendor/jdbc-driver/1.2.3/jdbc-driver-1.2.3.jar"; got != want {
			t.Errorf("request URL = %q, want %q", got, want)
		}
		if got := req.Header.Get("Authorization"); got != "Bearer test-adc-token" {
			t.Errorf("Authorization = %q", got)
		}
		return webArtifactResponse(req, http.StatusOK, "application/java-archive", jar), nil
	}, 0)

	got, err := registry.FingerprintArtifactRegistryRemote(context.Background(), webArtifactSetup(), webArtifactCandidate())
	if err != nil {
		t.Fatalf("FingerprintArtifactRegistryRemote() error = %v", err)
	}
	if want := "sha256:" + hex.EncodeToString(wantSum[:]); got != want {
		t.Fatalf("fingerprint = %q, want %q", got, want)
	}
	if requests != 1 {
		t.Fatalf("requests = %d, want 1", requests)
	}
}

func TestWebArtifactRegistryRemoteRejectsUntrustedInputsBeforeNetwork(t *testing.T) {
	called := false
	registry := webArtifactTestRegistry(t, func(req *http.Request) (*http.Response, error) {
		called = true
		return nil, nil
	}, 0)

	for _, test := range []struct {
		name      string
		setup     WebCloudSetupRecord
		candidate WebDriverCandidate
	}{
		{name: "unverified setup", setup: func() WebCloudSetupRecord {
			setup := webArtifactSetup()
			setup.Status = webCloudSetupDegraded
			return setup
		}(), candidate: webArtifactCandidate()},
		{name: "repository not setup bound", setup: func() WebCloudSetupRecord {
			setup := webArtifactSetup()
			setup.RepositoryName = "other-driver-remote"
			return setup
		}(), candidate: webArtifactCandidate()},
		{name: "coordinate version injection", setup: webArtifactSetup(), candidate: WebDriverCandidate{Coordinates: "com.vendor:jdbc-driver:1.2.3", Version: "1.2.3"}},
		{name: "path traversal version", setup: webArtifactSetup(), candidate: WebDriverCandidate{Coordinates: "com.vendor:jdbc-driver", Version: "../1.2.3"}},
		{name: "path traversal group", setup: webArtifactSetup(), candidate: WebDriverCandidate{Coordinates: "com..vendor:jdbc-driver", Version: "1.2.3"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			if _, err := registry.FingerprintArtifactRegistryRemote(context.Background(), test.setup, test.candidate); err == nil {
				t.Fatal("FingerprintArtifactRegistryRemote() error = nil, want rejection")
			}
		})
	}
	if called {
		t.Fatal("transport was called for invalid input")
	}
}

func TestWebArtifactRegistryRemoteRejectsRedirectCrossHostOversizeAndNonJAR(t *testing.T) {
	jar := []byte("PK\x03\x04jar")
	for _, test := range []struct {
		name     string
		maxBytes int64
		response func(*http.Request) (*http.Response, error)
	}{
		{
			name: "redirect",
			response: func(req *http.Request) (*http.Response, error) {
				response := webArtifactResponse(req, http.StatusFound, "text/html", nil)
				response.Header.Set("Location", "https://other.example.test/driver.jar")
				return response, nil
			},
		},
		{
			name: "cross host response",
			response: func(req *http.Request) (*http.Response, error) {
				response := webArtifactResponse(req, http.StatusOK, "application/java-archive", jar)
				response.Request = &http.Request{URL: &url.URL{Scheme: "https", Host: "other.example.test"}}
				return response, nil
			},
		},
		{
			name:     "declared oversize",
			maxBytes: 4,
			response: func(req *http.Request) (*http.Response, error) {
				return webArtifactResponse(req, http.StatusOK, "application/java-archive", jar), nil
			},
		},
		{
			name: "non jar type",
			response: func(req *http.Request) (*http.Response, error) {
				return webArtifactResponse(req, http.StatusOK, "text/html", jar), nil
			},
		},
		{
			name: "non jar magic",
			response: func(req *http.Request) (*http.Response, error) {
				return webArtifactResponse(req, http.StatusOK, "application/octet-stream", []byte("not-a-jar")), nil
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			registry := webArtifactTestRegistry(t, test.response, test.maxBytes)
			if _, err := registry.FingerprintArtifactRegistryRemote(context.Background(), webArtifactSetup(), webArtifactCandidate()); err == nil {
				t.Fatal("FingerprintArtifactRegistryRemote() error = nil, want rejection")
			}
		})
	}
}

func TestWebArtifactRegistryRemoteRejectsStreamingOversize(t *testing.T) {
	jar := []byte("PK\x03\x04" + strings.Repeat("x", 10))
	registry := webArtifactTestRegistry(t, func(req *http.Request) (*http.Response, error) {
		response := webArtifactResponse(req, http.StatusOK, "application/java-archive", jar)
		response.ContentLength = -1
		return response, nil
	}, 8)

	if _, err := registry.FingerprintArtifactRegistryRemote(context.Background(), webArtifactSetup(), webArtifactCandidate()); err == nil {
		t.Fatal("FingerprintArtifactRegistryRemote() error = nil, want streaming size rejection")
	}
}

func TestWebArtifactRegistryRemoteRejectsInvalidConfiguration(t *testing.T) {
	_, err := NewWebArtifactRegistryRemote(context.Background(), WebArtifactRegistryRemoteConfig{
		MaxArtifactBytes: 3,
		TokenSource:      oauth2.StaticTokenSource(&oauth2.Token{AccessToken: "test"}),
	})
	if !errors.Is(err, errWebArtifactConfiguration) {
		t.Fatalf("NewWebArtifactRegistryRemote() error = %v, want configuration error", err)
	}
}
