package main

// firestore_state.go adapts the existing integrity-checked snapshot stores to
// Firestore. Bodies are gzip-compressed and split into immutable documents so
// snapshots and exact replay manifests are not constrained by Firestore's
// per-document size limit. A transactional head-document swap supplies the
// compare-and-swap boundary required by the stores.

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"
	"time"

	"cloud.google.com/go/firestore"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

const firestoreChunkBytes = 700 << 10

var firestoreNamespacePattern = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_-]{0,63}$`)

type firestoreObjectStore struct {
	client     *firestore.Client
	collection *firestore.CollectionRef
}

type firestoreObjectHead struct {
	Name       string    `firestore:"name"`
	Revision   int64     `firestore:"revision"`
	Digest     string    `firestore:"digest"`
	Size       int64     `firestore:"size"`
	ChunkCount int       `firestore:"chunkCount"`
	Encoding   string    `firestore:"encoding"`
	UpdatedAt  time.Time `firestore:"updatedAt"`
}

type firestoreObjectChunk struct {
	Index int    `firestore:"index"`
	Body  []byte `firestore:"body"`
}

func newFirestoreObjectStore(ctx context.Context, projectID, databaseID, namespace string) (*firestoreObjectStore, error) {
	projectID = strings.TrimSpace(projectID)
	databaseID = strings.TrimSpace(databaseID)
	namespace = strings.TrimSpace(namespace)
	if projectID == "" || databaseID == "" || !firestoreNamespacePattern.MatchString(namespace) {
		return nil, errors.New("hosted state: invalid Firestore configuration")
	}
	client, err := firestore.NewClientWithDatabase(ctx, projectID, databaseID)
	if err != nil {
		return nil, errors.New("hosted state: Firestore client unavailable")
	}
	return &firestoreObjectStore{client: client, collection: client.Collection(namespace + "_objects")}, nil
}

func firestoreObjectName(name string) (string, error) {
	name = strings.Trim(strings.TrimSpace(name), "/")
	if name == "" || len(name) > 512 || strings.Contains(name, "..") || strings.ContainsAny(name, "\r\n") {
		return "", errors.New("hosted state: invalid object name")
	}
	return name, nil
}

func firestoreObjectID(name string) string {
	digest := sha256.Sum256([]byte(name))
	return hex.EncodeToString(digest[:])
}

func firestoreRevision() (int64, error) {
	var raw [8]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return 0, errors.New("hosted state: revision unavailable")
	}
	revision := int64(binary.BigEndian.Uint64(raw[:]) & ((1 << 63) - 1))
	if revision == 0 {
		revision = 1
	}
	return revision, nil
}

func firestoreEncodeBody(body []byte) ([]byte, []firestoreObjectChunk, error) {
	if len(body) > hostedMaxStateBytes {
		return nil, nil, errors.New("hosted state: object exceeds size limit")
	}
	var compressed bytes.Buffer
	writer := gzip.NewWriter(&compressed)
	if _, err := writer.Write(body); err != nil {
		return nil, nil, errors.New("hosted state: object compression failed")
	}
	if err := writer.Close(); err != nil {
		return nil, nil, errors.New("hosted state: object compression failed")
	}
	encoded := compressed.Bytes()
	chunks := make([]firestoreObjectChunk, 0, (len(encoded)+firestoreChunkBytes-1)/firestoreChunkBytes)
	for offset := 0; offset < len(encoded); offset += firestoreChunkBytes {
		end := offset + firestoreChunkBytes
		if end > len(encoded) {
			end = len(encoded)
		}
		chunks = append(chunks, firestoreObjectChunk{Index: len(chunks), Body: append([]byte(nil), encoded[offset:end]...)})
	}
	if len(chunks) == 0 {
		chunks = append(chunks, firestoreObjectChunk{Index: 0, Body: []byte{}})
	}
	return encoded, chunks, nil
}

func firestoreDecodeBody(encoded []byte, expectedSize, limit int64) ([]byte, error) {
	if expectedSize < 0 || expectedSize > limit {
		return nil, errors.New("hosted state: object exceeds size limit")
	}
	reader, err := gzip.NewReader(bytes.NewReader(encoded))
	if err != nil {
		return nil, errors.New("hosted state: object encoding is invalid")
	}
	body, readErr := io.ReadAll(io.LimitReader(reader, limit+1))
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || int64(len(body)) != expectedSize || int64(len(body)) > limit {
		return nil, errors.New("hosted state: object could not be read safely")
	}
	return body, nil
}

func firestoreChunkID(revision int64, index int) string {
	return fmt.Sprintf("%016x-%04d", uint64(revision), index)
}

func (s *firestoreObjectStore) read(ctx context.Context, name string, limit int64) ([]byte, int64, error) {
	name, err := firestoreObjectName(name)
	if err != nil {
		return nil, 0, err
	}
	headRef := s.collection.Doc(firestoreObjectID(name))
	snapshot, err := headRef.Get(ctx)
	if err != nil {
		return nil, 0, err
	}
	var head firestoreObjectHead
	if err := snapshot.DataTo(&head); err != nil || head.Name != name || head.Revision <= 0 || head.Encoding != "gzip" || head.ChunkCount < 1 || head.ChunkCount > 500 {
		return nil, 0, errors.New("hosted state: object metadata is invalid")
	}
	refs := make([]*firestore.DocumentRef, head.ChunkCount)
	for index := range refs {
		refs[index] = headRef.Collection("chunks").Doc(firestoreChunkID(head.Revision, index))
	}
	snapshots, err := s.client.GetAll(ctx, refs)
	if err != nil {
		return nil, 0, errors.New("hosted state: object chunks unavailable")
	}
	var encoded bytes.Buffer
	for index, chunkSnapshot := range snapshots {
		var chunk firestoreObjectChunk
		if err := chunkSnapshot.DataTo(&chunk); err != nil || chunk.Index != index || len(chunk.Body) > firestoreChunkBytes {
			return nil, 0, errors.New("hosted state: object chunk is invalid")
		}
		encoded.Write(chunk.Body)
	}
	body, err := firestoreDecodeBody(encoded.Bytes(), head.Size, limit)
	if err != nil {
		return nil, 0, err
	}
	digest := sha256.Sum256(body)
	if "sha256:"+hex.EncodeToString(digest[:]) != head.Digest {
		return nil, 0, errors.New("hosted state: object digest mismatch")
	}
	return body, head.Revision, nil
}

func (s *firestoreObjectStore) write(ctx context.Context, name string, body []byte, generation int64, createOnly bool) (int64, error) {
	name, err := firestoreObjectName(name)
	if err != nil {
		return 0, err
	}
	_, chunks, err := firestoreEncodeBody(body)
	if err != nil {
		return 0, err
	}
	revision, err := firestoreRevision()
	if err != nil {
		return 0, err
	}
	headRef := s.collection.Doc(firestoreObjectID(name))
	batch := s.client.Batch()
	for index, chunk := range chunks {
		batch.Create(headRef.Collection("chunks").Doc(firestoreChunkID(revision, index)), chunk)
	}
	if _, err := batch.Commit(ctx); err != nil {
		return 0, errors.New("hosted state: object chunks could not be written")
	}
	digest := sha256.Sum256(body)
	head := firestoreObjectHead{
		Name: name, Revision: revision, Digest: "sha256:" + hex.EncodeToString(digest[:]),
		Size: int64(len(body)), ChunkCount: len(chunks), Encoding: "gzip", UpdatedAt: time.Now().UTC(),
	}
	err = s.client.RunTransaction(ctx, func(ctx context.Context, tx *firestore.Transaction) error {
		current, getErr := tx.Get(headRef)
		if createOnly {
			if getErr == nil {
				return errHostedConflict
			}
			if status.Code(getErr) != codes.NotFound {
				return getErr
			}
			return tx.Create(headRef, head)
		}
		if getErr != nil {
			return errHostedConflict
		}
		var currentHead firestoreObjectHead
		if current.DataTo(&currentHead) != nil || currentHead.Revision != generation {
			return errHostedConflict
		}
		return tx.Set(headRef, head)
	}, firestore.MaxAttempts(3))
	if err != nil {
		if errors.Is(err, errHostedConflict) || status.Code(err) == codes.AlreadyExists || status.Code(err) == codes.Aborted || status.Code(err) == codes.FailedPrecondition {
			return 0, errHostedConflict
		}
		return 0, errors.New("hosted state: object commit failed")
	}
	return revision, nil
}

func (s *firestoreObjectStore) loadOrCreate(ctx context.Context, name string, initial []byte) ([]byte, int64, error) {
	body, generation, err := s.read(ctx, name, hostedMaxStateBytes)
	if err == nil {
		return body, generation, nil
	}
	if status.Code(err) != codes.NotFound {
		return nil, 0, err
	}
	if _, err := s.write(ctx, name, initial, 0, true); err != nil && !errors.Is(err, errHostedConflict) {
		return nil, 0, err
	}
	return s.read(ctx, name, hostedMaxStateBytes)
}
