import { MissionControlClient, MissionControlClientError } from "./client.ts";
import {
  buildMissionControlView,
  canApprove,
  MIGRATION_SCHEMA_VERSION,
} from "./model.ts";
import type {
  MigrationRun,
  MigrationSseEvent,
} from "./model.ts";

const DIGEST_A = `sha256:${"a".repeat(64)}`;
const DIGEST_B = `sha256:${"b".repeat(64)}`;
const DIGEST_C = `sha256:${"c".repeat(64)}`;
const DIGEST_D = `sha256:${"d".repeat(64)}`;

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

function equal<T>(actual: T, expected: T, message: string): void {
  if (actual !== expected) throw new Error(`${message}: expected ${String(expected)}, got ${String(actual)}`);
}

function approvalRun(): MigrationRun {
  return {
    schemaVersion: MIGRATION_SCHEMA_VERSION,
    runId: "mig_PORTFOLIO0001",
    portfolioName: "Legacy ERP Portfolio",
    state: "awaiting_approval",
    // Deliberately shuffled: the view must always emit canonical lane order.
    sources: [
      {
        sourceId: "btrieve",
        hostname: "legacy-btrieve-db",
        state: "awaiting_approval",
        recordsRead: 1,
        recordsWritten: 0,
        recordsRejected: 0,
        planDigest: DIGEST_C,
      },
      {
        sourceId: "jde",
        hostname: "legacy-jde-db",
        state: "awaiting_approval",
        recordsRead: 4,
        recordsWritten: 0,
        recordsRejected: 0,
        planDigest: DIGEST_A,
      },
      {
        sourceId: "maxdb",
        hostname: "legacy-maxdb",
        state: "awaiting_approval",
        recordsRead: 4,
        recordsWritten: 0,
        recordsRejected: 0,
        planDigest: DIGEST_B,
      },
    ],
    portfolioPlanDigest: DIGEST_D,
    createdAt: "2026-08-26T14:00:00.000Z",
    updatedAt: "2026-08-26T14:02:00.000Z",
  };
}

function evidenceEvents(runId: string): MigrationSseEvent[] {
  return [
    {
      schemaVersion: MIGRATION_SCHEMA_VERSION,
      eventId: "evt_SOURCEEVENT01",
      runId,
      sourceId: "jde",
      eventType: "source.plan.ready",
      timestamp: "2026-08-26T14:02:00.000Z",
      summary: "JDE transform plan is ready for portfolio approval.",
      evidenceReferences: [{ artifactId: "art_jde-plan-001", kind: "transform_plan", digest: DIGEST_A }],
      state: "awaiting_approval",
    },
    {
      schemaVersion: MIGRATION_SCHEMA_VERSION,
      eventId: "evt_PORTFOLIOEV01",
      runId,
      eventType: "portfolio.awaiting_approval",
      timestamp: "2026-08-26T14:02:01.000Z",
      summary: "All three source plans are ready for one portfolio decision.",
      evidenceReferences: [{ artifactId: "art_audit-log-001", kind: "audit_log", digest: DIGEST_D }],
      state: "awaiting_approval",
    },
  ];
}

function testModelProjection(): void {
  const run = approvalRun();
  const view = buildMissionControlView(run, evidenceEvents(run.runId));

  equal(view.lanes.map((lane) => lane.sourceId).join(","), "jde,maxdb,btrieve", "lane order");
  equal(view.lanes[0]?.counts.read, 4, "JDE read count");
  equal(view.lanes[0]?.evidence.length, 1, "source evidence count");
  equal(view.lanes[1]?.evidence.length, 0, "MaxDB must not inherit JDE evidence");
  equal(view.portfolioEvidence.length, 1, "portfolio evidence count");
  assert(view.portfolioEvidence[0]?.sourceId === undefined, "portfolio evidence must stay unscoped");
  assert(view.approvalEnabled, "complete trusted gate should enable approval");
  assert(canApprove(view), "canApprove should independently accept a valid view");

  const disconnected = buildMissionControlView(run, evidenceEvents(run.runId), "disconnected");
  assert(!disconnected.approvalEnabled, "disconnected data must not be approvable");
  assert(disconnected.approvalBlockers.includes("connection_disconnected"), "disconnect blocker missing");
  assert(!canApprove(disconnected), "canApprove must reject a disconnected view");

  const invalidDigest = approvalRun();
  invalidDigest.sources[0] = { ...invalidDigest.sources[0]!, planDigest: "not-a-digest" };
  const invalidView = buildMissionControlView(invalidDigest, []);
  assert(!invalidView.approvalEnabled, "malformed source digest must block approval");
  assert(invalidView.approvalBlockers.includes("source_digest_invalid"), "digest blocker missing");
}

function splitBytes(bytes: Uint8Array, boundaries: readonly number[]): Uint8Array[] {
  const chunks: Uint8Array[] = [];
  let start = 0;
  for (const end of boundaries) {
    chunks.push(bytes.slice(start, end));
    start = end;
  }
  chunks.push(bytes.slice(start));
  return chunks.filter((chunk) => chunk.byteLength > 0);
}

function sseResponse(event: MigrationSseEvent): Response {
  const payload = `retry: 250\r\n\r\nid: ${event.eventId}\r\nevent: ${event.eventType}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`;
  const encoded = new TextEncoder().encode(payload);
  const chunks = splitBytes(encoded, Array.from({ length: encoded.length - 1 }, (_, index) => index + 1));
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream; charset=utf-8" } },
  );
}

async function testAuthenticatedResumption(): Promise<void> {
  const runId = "mig_PORTFOLIO0001";
  const baseEvent = evidenceEvents(runId)[0]!;
  assert(baseEvent.eventType === "source.plan.ready", "expected a source-scoped fixture event");
  const secondEvent: MigrationSseEvent = {
    ...baseEvent,
    eventId: "evt_SOURCEEVENT02",
    sourceId: "maxdb",
    summary: "MaxDB transform plan is ready for portfolio approval.",
    evidenceReferences: [{ artifactId: "art_maxdb-plan01", kind: "transform_plan", digest: DIGEST_B }],
  };
  const authorizationHeaders: string[] = [];
  const cursors: Array<string | null> = [];
  const connectionStates: string[] = [];
  let requestCount = 0;
  const fakeFetch = (async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const headers = new Headers(init?.headers);
    authorizationHeaders.push(headers.get("Authorization") ?? "");
    cursors.push(headers.get("Last-Event-ID"));
    requestCount += 1;
    return sseResponse(requestCount === 1 ? baseEvent : secondEvent);
  }) as typeof fetch;

  const client = new MissionControlClient({ baseUrl: "http://mission-control.test", token: "test-token", fetchImpl: fakeFetch });
  const stream = client.streamEvents(runId, {
    onConnectionStateChange: (state) => connectionStates.push(state),
  });
  const first = await stream.next();
  equal(first.value?.eventId, baseEvent.eventId, "first event id");
  const second = await stream.next();
  equal(second.value?.eventId, secondEvent.eventId, "second event id");
  await stream.return();

  equal(authorizationHeaders[0], "Bearer test-token", "authenticated first request");
  equal(authorizationHeaders[1], "Bearer test-token", "authenticated resumed request");
  equal(cursors[0], null, "first cursor");
  equal(cursors[1], baseEvent.eventId, "exact resumed cursor");
  assert(!connectionStates.includes("reconnecting"), "clean bounded replay must not report reconnecting");
  assert(!connectionStates.includes("stale"), "clean bounded replay must not report stale");
  client.close();
  assert(client.isClosed, "close should permanently close the client");
}

async function testErrorsDoNotLeakToken(): Promise<void> {
  const secret = "do-not-reflect-this-token";
  const rejectingFetch = (async (): Promise<Response> => {
    throw new Error(secret);
  }) as typeof fetch;
  const client = new MissionControlClient({ baseUrl: "", token: secret, fetchImpl: rejectingFetch });
  try {
    await client.getMigration("mig_PORTFOLIO0001");
    throw new Error("network failure should reject");
  } catch (error) {
    assert(error instanceof MissionControlClientError, "expected structured client error");
    equal(error.code, "network_error", "network error code");
    assert(!error.message.includes(secret), "structured error leaked the bearer token");
  }
}

async function testFrozenRestMethods(): Promise<void> {
  const run = approvalRun();
  const calls: Array<{ url: string; method: string; authorization: string | null }> = [];
  let requestIndex = 0;
  const responses: unknown[] = [
    run,
    run,
    {
      schemaVersion: MIGRATION_SCHEMA_VERSION,
      approvalId: "apr_APPROVAL000001",
      runId: run.runId,
      planDigest: DIGEST_D,
      decision: "approve",
      resultingState: "approved",
      decidedBy: "migration-operator",
      decidedAt: "2026-08-26T14:03:00.000Z",
    },
  ];
  const statuses = [202, 200, 200];
  const fakeFetch = (async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const headers = new Headers(init?.headers);
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      authorization: headers.get("Authorization"),
    });
    const response = new Response(JSON.stringify(responses[requestIndex]), {
      status: statuses[requestIndex],
      headers: { "Content-Type": "application/json" },
    });
    requestIndex += 1;
    return response;
  }) as typeof fetch;
  const client = new MissionControlClient({ baseUrl: "https://mission-control.test/", token: "rest-token", fetchImpl: fakeFetch });

  await client.createMigration({
    schemaVersion: MIGRATION_SCHEMA_VERSION,
    portfolioName: run.portfolioName,
    sources: [
      { sourceId: "jde", hostname: "legacy-jde-db" },
      { sourceId: "maxdb", hostname: "legacy-maxdb" },
      { sourceId: "btrieve", hostname: "legacy-btrieve-db" },
    ],
    requestedBy: "migration-operator",
  });
  await client.getMigration(run.runId);
  await client.approveMigration(run.runId, {
    schemaVersion: MIGRATION_SCHEMA_VERSION,
    planDigest: DIGEST_D,
    decision: "approve",
    decidedBy: "migration-operator",
  });

  equal(calls[0]?.url, "https://mission-control.test/api/v1/migrations", "create endpoint");
  equal(calls[0]?.method, "POST", "create method");
  equal(calls[1]?.url, `https://mission-control.test/api/v1/migrations/${run.runId}`, "get endpoint");
  equal(calls[1]?.method, "GET", "get method");
  equal(calls[2]?.url, `https://mission-control.test/api/v1/migrations/${run.runId}/approval`, "approval endpoint");
  equal(calls[2]?.method, "POST", "approval method");
  assert(calls.every((call) => call.authorization === "Bearer rest-token"), "REST request omitted bearer authentication");
}

async function testProxyModeOmitsBrowserCredential(): Promise<void> {
  const run = approvalRun();
  let authorization: string | null = "not-called";
  const fakeFetch = (async (_input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    authorization = new Headers(init?.headers).get("Authorization");
    return new Response(JSON.stringify(run), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  const client = new MissionControlClient({ baseUrl: "", fetchImpl: fakeFetch });

  await client.getMigration(run.runId);
  equal(authorization, null, "same-origin proxy mode must omit browser Authorization");
}

async function testNativeFetchUsesGlobalReceiver(): Promise<void> {
  const originalFetch = globalThis.fetch;
  const run = approvalRun();
  let usedGlobalReceiver = false;
  globalThis.fetch = async function (this: unknown): Promise<Response> {
    usedGlobalReceiver = this === globalThis;
    return new Response(JSON.stringify(run), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } as typeof fetch;
  try {
    const client = new MissionControlClient({ baseUrl: "" });
    await client.getMigration(run.runId);
    assert(usedGlobalReceiver, "native fetch receiver must be globalThis");
    client.close();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function testMigrationReadRetriesTransportFailure(): Promise<void> {
  const run = approvalRun();
  let requestCount = 0;
  const retryCodes: string[] = [];
  const fakeFetch = (async (): Promise<Response> => {
    requestCount += 1;
    if (requestCount === 1) throw new Error("simulated startup race");
    return new Response(JSON.stringify(run), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
  const client = new MissionControlClient({ baseUrl: "", fetchImpl: fakeFetch });
  const loaded = await client.getMigrationWithRetry(run.runId, {
    retryMs: 1,
    onRetry: (error) => retryCodes.push(error.code),
  });

  equal(loaded?.runId, run.runId, "retried run id");
  equal(requestCount, 2, "transport retry request count");
  equal(retryCodes.join(","), "network_error", "transport retry code");
  client.close();
}

async function testTransportFailureStaysStaleUntilRecovery(): Promise<void> {
  const runId = "mig_PORTFOLIO0001";
  const firstEvent = evidenceEvents(runId)[0]!;
  assert(firstEvent.eventType === "source.plan.ready", "expected a source-scoped fixture event");
  const recoveredEvent: MigrationSseEvent = {
    ...firstEvent,
    eventId: "evt_SOURCEEVENT03",
    sourceId: "btrieve",
    summary: "Btrieve transform plan is ready after transport recovery.",
    evidenceReferences: [{ artifactId: "art_btrieve-plan1", kind: "transform_plan", digest: DIGEST_C }],
  };
  const connectionStates: string[] = [];
  let requestCount = 0;
  const fakeFetch = (async (): Promise<Response> => {
    requestCount += 1;
    if (requestCount === 2) throw new Error("simulated transport failure");
    return sseResponse(requestCount === 1 ? firstEvent : recoveredEvent);
  }) as typeof fetch;
  const client = new MissionControlClient({ baseUrl: "", fetchImpl: fakeFetch });
  const stream = client.streamEvents(runId, {
    onConnectionStateChange: (state) => connectionStates.push(state),
  });

  equal((await stream.next()).value?.eventId, firstEvent.eventId, "pre-failure event id");
  equal((await stream.next()).value?.eventId, recoveredEvent.eventId, "recovered event id");
  await stream.return();

  equal(
    connectionStates.join(","),
    "connecting,connected,stale,connected,disconnected",
    "transport health sequence",
  );
}

testModelProjection();
await testAuthenticatedResumption();
await testErrorsDoNotLeakToken();
await testFrozenRestMethods();
await testProxyModeOmitsBrowserCredential();
await testNativeFetchUsesGlobalReceiver();
await testMigrationReadRetriesTransportFailure();
await testTransportFailureStaysStaleUntilRecovery();
