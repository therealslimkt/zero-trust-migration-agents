package main

import (
	"context"
	"errors"
	"time"
)

const hostedMaxStateBytes = 64 << 20

var errHostedConflict = errors.New("hosted state: revision conflict")

// hostedObjectStore is the durable object-shaped boundary used by the frozen
// snapshot stores. Hosted implementations must provide compare-and-swap
// writes and create-only writes for immutable replay bundles.
type hostedObjectStore interface {
	read(context.Context, string, int64) ([]byte, int64, error)
	write(context.Context, string, []byte, int64, bool) (int64, error)
	loadOrCreate(context.Context, string, []byte) ([]byte, int64, error)
}

func hostedOperationContext() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), 30*time.Second)
}
