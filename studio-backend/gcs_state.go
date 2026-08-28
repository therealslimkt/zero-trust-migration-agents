package main

// gcs_state.go provides the hosted durability boundary for the control-plane
// and browser-BFF snapshots. Cloud Storage objects are replaced only when the
// generation read by this process still matches, so a concurrent revision can
// never silently overwrite newer state. Immutable replay bundles use a
// create-only precondition.

import (
	"context"
	"errors"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"cloud.google.com/go/storage"
	"google.golang.org/api/googleapi"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const gcsMaxStateBytes = 64 << 20

var (
	gcsBucketPattern = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$`)
	errGCSConflict   = errors.New("hosted state: generation conflict")
)

type gcsObjectStore struct {
	client *storage.Client
	bucket string
	prefix string
}

func newGCSObjectStore(ctx context.Context, bucket, prefix string) (*gcsObjectStore, error) {
	bucket = strings.TrimSpace(bucket)
	prefix = strings.Trim(strings.TrimSpace(prefix), "/")
	if !gcsBucketPattern.MatchString(bucket) || prefix == "" || len(prefix) > 512 || strings.Contains(prefix, "..") {
		return nil, errors.New("hosted state: invalid bucket or prefix")
	}
	client, err := storage.NewClient(ctx)
	if err != nil {
		return nil, errors.New("hosted state: storage client unavailable")
	}
	return &gcsObjectStore{client: client, bucket: bucket, prefix: prefix}, nil
}

func (s *gcsObjectStore) object(name string) (*storage.ObjectHandle, error) {
	name = strings.Trim(strings.TrimSpace(name), "/")
	if name == "" || len(name) > 512 || strings.Contains(name, "..") || strings.ContainsAny(name, "\r\n") {
		return nil, errors.New("hosted state: invalid object name")
	}
	return s.client.Bucket(s.bucket).Object(s.prefix + "/" + name), nil
}

func gcsPreconditionFailed(err error) bool {
	var apiErr *googleapi.Error
	return errors.As(err, &apiErr) && apiErr.Code == http.StatusPreconditionFailed || status.Code(err) == codes.FailedPrecondition
}

func (s *gcsObjectStore) read(ctx context.Context, name string, limit int64) ([]byte, int64, error) {
	obj, err := s.object(name)
	if err != nil {
		return nil, 0, err
	}
	attrs, err := obj.Attrs(ctx)
	if err != nil {
		return nil, 0, err
	}
	reader, err := obj.Generation(attrs.Generation).NewReader(ctx)
	if err != nil {
		return nil, 0, err
	}
	body, readErr := io.ReadAll(io.LimitReader(reader, limit+1))
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || len(body) > int(limit) {
		return nil, 0, errors.New("hosted state: object could not be read safely")
	}
	return body, attrs.Generation, nil
}

func (s *gcsObjectStore) write(ctx context.Context, name string, body []byte, generation int64, createOnly bool) (int64, error) {
	obj, err := s.object(name)
	if err != nil {
		return 0, err
	}
	conditions := storage.Conditions{GenerationMatch: generation}
	if createOnly {
		conditions = storage.Conditions{DoesNotExist: true}
	}
	writer := obj.If(conditions).NewWriter(ctx)
	writer.ContentType = "application/json"
	writer.CacheControl = "no-store"
	if _, err := writer.Write(body); err != nil {
		_ = writer.Close()
		if gcsPreconditionFailed(err) {
			return 0, errGCSConflict
		}
		return 0, errors.New("hosted state: object write failed")
	}
	if err := writer.Close(); err != nil {
		if gcsPreconditionFailed(err) {
			return 0, errGCSConflict
		}
		return 0, errors.New("hosted state: object commit failed")
	}
	attrs := writer.Attrs()
	if attrs == nil || attrs.Generation <= 0 {
		return 0, errors.New("hosted state: object generation unavailable")
	}
	return attrs.Generation, nil
}

func (s *gcsObjectStore) loadOrCreate(ctx context.Context, name string, initial []byte) ([]byte, int64, error) {
	body, generation, err := s.read(ctx, name, gcsMaxStateBytes)
	if err == nil {
		return body, generation, nil
	}
	if !errors.Is(err, storage.ErrObjectNotExist) {
		return nil, 0, err
	}
	if _, err := s.write(ctx, name, initial, 0, true); err != nil && !errors.Is(err, errGCSConflict) {
		return nil, 0, err
	}
	return s.read(ctx, name, gcsMaxStateBytes)
}

func gcsOperationContext() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 30*time.Second)
}
