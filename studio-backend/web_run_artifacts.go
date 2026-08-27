package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
)

const webMaxRunArtifactBytes = 16 << 20

// WebRunArtifactStore exposes a read-only, deployment-owned directory. The
// layout is <run>/artifacts/<artifact-id> and <run>/sources/<source-id>.json.
// os.Root keeps every open beneath the configured directory even when an
// attacker can create symlinks or race path components.
type WebRunArtifactStore struct {
	root *os.Root
}

func OpenWebRunArtifactStore(directory string) (*WebRunArtifactStore, error) {
	if directory == "" {
		return nil, errors.New("web artifacts: a directory is required")
	}
	root, err := os.OpenRoot(directory)
	if err != nil {
		return nil, fmt.Errorf("web artifacts: open root: %w", err)
	}
	return &WebRunArtifactStore{root: root}, nil
}

func (s *WebRunArtifactStore) Close() error {
	if s == nil || s.root == nil {
		return nil
	}
	return s.root.Close()
}

func (s *WebRunArtifactStore) readBounded(path string) ([]byte, error) {
	if s == nil || s.root == nil {
		return nil, os.ErrNotExist
	}
	file, err := s.root.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > webMaxRunArtifactBytes {
		return nil, errors.New("web artifacts: invalid artifact file")
	}
	body, err := io.ReadAll(io.LimitReader(file, webMaxRunArtifactBytes+1))
	if err != nil || len(body) > webMaxRunArtifactBytes {
		return nil, errors.New("web artifacts: artifact exceeds size limit")
	}
	return body, nil
}

func (s *WebRunArtifactStore) ReadPublicationArtifact(_ context.Context, runID, artifactID string) ([]byte, error) {
	if !webRunIDPattern.MatchString(runID) || !webArtifactPattern.MatchString(artifactID) {
		return nil, os.ErrNotExist
	}
	return s.readBounded(runID + "/artifacts/" + artifactID)
}

func (s *WebRunArtifactStore) ReadLiveSourceDetail(_ context.Context, runID, sourceID string) (*WebSourceReplay, error) {
	if !webRunIDPattern.MatchString(runID) {
		return nil, os.ErrNotExist
	}
	if _, ok := cpCanonicalHostname(sourceID); !ok {
		return nil, os.ErrNotExist
	}
	body, err := s.readBounded(runID + "/sources/" + sourceID + ".json")
	if err != nil {
		return nil, err
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	var detail WebSourceReplay
	if err := decoder.Decode(&detail); err != nil {
		return nil, errors.New("web artifacts: invalid source detail")
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return nil, errors.New("web artifacts: source detail has trailing content")
	}
	return &detail, nil
}
