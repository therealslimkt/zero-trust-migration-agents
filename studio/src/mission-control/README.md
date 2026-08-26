# Mission Control domain layer

This directory projects the frozen migration API into the three simultaneous
Mission Control lanes. It contains no simulated state, progress timers, raw
record values, or vendor-specific connection details.

## Model

`model.ts` mirrors contract version `1.0.0` and exports:

- `SOURCE_ORDER` and `SOURCE_PRESENTATION` for the canonical JDE, MaxDB, and
  Btrieve lanes;
- the closed REST/SSE wire types;
- `buildMissionControlView(run, events, connectionState)`; and
- `canApprove(view)`.

The builder preserves persisted event order, binds source evidence only to its
source, and keeps portfolio evidence separate. A returned view always has all
three lanes in canonical order. It refuses malformed source sets instead of
inventing missing progress.

The UI can consume these stable fields directly:

```ts
const view = buildMissionControlView(run, events, connectionState);

view.runId;
view.portfolioName;
view.state;
view.planDigest;
view.approvalEnabled;
view.approvalBlockers;
view.lanes;
view.portfolioEvidence;
```

Each lane provides presentation metadata, the real source state and counts,
plan digest, source-scoped evidence and events, failure code, and blocking
status.

## Authenticated client

`MissionControlClient` exposes the frozen API operation names plus short
aliases:

```ts
const client = new MissionControlClient({ baseUrl, token });
const run = await client.getMigration(runId); // alias: get

for await (const event of client.streamEvents(runId, {
  lastEventId,
  signal,
  onConnectionStateChange: setConnectionState,
})) {
  // Append once by event.eventId, then rebuild the view.
}

await client.approveMigration(runId, approvalRequest); // alias: approve
client.close();
```

The stream uses authenticated `fetch`, not browser `EventSource`. It parses SSE
incrementally across chunk boundaries, honors server retry hints within a
250–10,000 ms bound, and reconnects with the exact last validated SSE ID. An
abort signal ends one stream; `client.close()` permanently closes the client
and aborts every active stream.

All wire responses are checked against the closed vocabularies before they
reach the UI. `MissionControlClientError` contains only fixed local messages,
closed codes, an optional HTTP status, and retryability; it never includes the
bearer token, request headers, URL, response body, or remote exception text.

## Validation

`model.test.ts` is dependency-free and runs on Node versions that support TypeScript
type stripping:

```bash
node --experimental-strip-types src/mission-control/model.test.ts
```

The normal Studio build and lint commands also type-check and lint this layer.
