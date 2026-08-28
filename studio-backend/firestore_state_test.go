package main

import (
	"bytes"
	"testing"
)

func TestFirestoreBodyCodecRoundTripAcrossChunks(t *testing.T) {
	body := bytes.Repeat([]byte("migration-evidence-0123456789\n"), 90000)
	encoded, chunks, err := firestoreEncodeBody(body)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if len(encoded) == 0 || len(chunks) == 0 {
		t.Fatal("expected encoded body and chunks")
	}
	var joined []byte
	for index, chunk := range chunks {
		if chunk.Index != index {
			t.Fatalf("chunk %d has index %d", index, chunk.Index)
		}
		if len(chunk.Body) > firestoreChunkBytes {
			t.Fatalf("chunk %d exceeds Firestore-safe size", index)
		}
		joined = append(joined, chunk.Body...)
	}
	decoded, err := firestoreDecodeBody(joined, int64(len(body)), hostedMaxStateBytes)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if !bytes.Equal(decoded, body) {
		t.Fatal("round-trip body mismatch")
	}
}

func TestFirestoreBodyCodecRejectsLimitAndTruncation(t *testing.T) {
	if _, _, err := firestoreEncodeBody(make([]byte, hostedMaxStateBytes+1)); err == nil {
		t.Fatal("expected oversized body rejection")
	}
	encoded, _, err := firestoreEncodeBody([]byte(`{"status":"awaiting_approval"}`))
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	if _, err := firestoreDecodeBody(encoded[:len(encoded)-1], 30, hostedMaxStateBytes); err == nil {
		t.Fatal("expected truncated body rejection")
	}
}

func TestFirestoreObjectNameValidation(t *testing.T) {
	for _, name := range []string{"", "../state.json", "bad\nname"} {
		if _, err := firestoreObjectName(name); err == nil {
			t.Fatalf("expected %q to be rejected", name)
		}
	}
	if got, err := firestoreObjectName("/web-state.json.bundles/sha256.json/"); err != nil || got != "web-state.json.bundles/sha256.json" {
		t.Fatalf("valid object name: got %q, err %v", got, err)
	}
}
