import {
  MIGRATION_SCHEMA_VERSION,
  SOURCE_ORDER,
  SOURCE_PRESENTATION,
} from "./model.ts";
import type {
  ApprovalRequest,
  ApprovalResponse,
  ConnectionState,
  CreateMigrationRequest,
  EvidenceKind,
  EvidenceReference,
  MigrationRun,
  MigrationSseEvent,
  PortfolioEventType,
  RunState,
  SourceEventType,
  SourceId,
  SourceProgress,
} from "./model.ts";

const RUN_ID_PATTERN = /^mig_[A-Za-z0-9]{12,64}$/;
const EVENT_ID_PATTERN = /^evt_[A-Za-z0-9]{12,64}$/;
const APPROVAL_ID_PATTERN = /^apr_[A-Za-z0-9]{12,64}$/;
const ARTIFACT_ID_PATTERN = /^art_[A-Za-z0-9._-]{8,128}$/;
const DIGEST_PATTERN = /^sha256:[a-f0-9]{64}$/;
const FAILURE_CODE_PATTERN = /^[A-Z][A-Z0-9_]{2,63}$/;
const PORTFOLIO_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 _.-]*$/;
const ACTOR_PATTERN = /^[A-Za-z0-9][A-Za-z0-9@._ -]*$/;

const DEFAULT_RETRY_MS = 2_000;
const MIN_RETRY_MS = 250;
const MAX_RETRY_MS = 10_000;
const MAX_SSE_FIELD_CHARS = 256 * 1024;
const RFC3339_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const RUN_STATES = new Set<RunState>([
  "created",
  "inventorying",
  "redacting",
  "planning",
  "awaiting_approval",
  "approved",
  "executing",
  "verifying",
  "completed",
  "failed",
  "cancelled",
]);

const EVIDENCE_KINDS = new Set<EvidenceKind>([
  "source_manifest",
  "redaction_report",
  "transform_plan",
  "dataflow_job",
  "bigquery_table",
  "reconciliation",
  "audit_log",
]);

const SOURCE_EVENT_TYPES = new Set<SourceEventType>([
  "source.inventory.started",
  "source.inventory.completed",
  "source.redaction.completed",
  "source.plan.ready",
  "source.execution.started",
  "source.execution.completed",
  "source.verification.completed",
  "source.failed",
]);

const PORTFOLIO_EVENT_TYPES = new Set<PortfolioEventType>([
  "migration.created",
  "portfolio.awaiting_approval",
  "portfolio.approved",
  "portfolio.rejected",
  "migration.completed",
  "migration.failed",
  "migration.cancelled",
]);

export interface MissionControlClientOptions {
  baseUrl: string;
  /**
   * Optional for a same-origin browser client whose local server-side proxy
   * authenticates upstream. Direct API clients must still provide a token.
   */
  token?: string;
  fetchImpl?: typeof fetch;
}

export interface StreamEventsOptions {
  lastEventId?: string;
  signal?: AbortSignal;
  onConnectionStateChange?: (state: ConnectionState) => void;
}

export type MissionControlClientErrorCode =
  | "invalid_configuration"
  | "client_closed"
  | "invalid_request"
  | "network_error"
  | "unauthorized"
  | "not_found"
  | "conflict"
  | "request_rejected"
  | "server_error"
  | "invalid_response";

const ERROR_MESSAGES: Readonly<Record<MissionControlClientErrorCode, string>> = Object.freeze({
  invalid_configuration: "The Mission Control client configuration is invalid.",
  client_closed: "The Mission Control client is closed.",
  invalid_request: "The migration request is invalid.",
  network_error: "Mission Control could not reach the migration service.",
  unauthorized: "Mission Control is not authorized to access the migration service.",
  not_found: "The requested migration resource was not found.",
  conflict: "The migration request conflicts with the current trusted state.",
  request_rejected: "The migration service rejected the request.",
  server_error: "The migration service could not complete the request.",
  invalid_response: "The migration service returned an invalid response.",
});

/**
 * Safe, closed client error. It deliberately excludes URL, headers, bodies,
 * remote text, thrown fetch messages, and causes so a bearer token can never
 * be reflected through the error surface.
 */
export class MissionControlClientError extends Error {
  readonly code: MissionControlClientErrorCode;
  readonly status?: number;
  readonly retryable: boolean;

  constructor(code: MissionControlClientErrorCode, status?: number, retryable = false) {
    super(ERROR_MESSAGES[code]);
    this.name = "MissionControlClientError";
    this.code = code;
    this.retryable = retryable;
    if (status !== undefined) this.status = status;
  }
}

interface ParsedSseFrame {
  id?: string;
  event?: string;
  data?: string;
  retryMs?: number;
}

class IncrementalSseParser {
  private buffer = "";
  private dataLines: string[] = [];
  private dataChars = 0;
  private eventName: string | undefined;
  private eventId: string | undefined;
  private retryMs: number | undefined;
  private sawEventId = false;

  feed(chunk: string): ParsedSseFrame[] {
    this.buffer += chunk;
    const frames: ParsedSseFrame[] = [];
    let cursor = 0;

    while (cursor < this.buffer.length) {
      let lineEnd = cursor;
      while (lineEnd < this.buffer.length && this.buffer[lineEnd] !== "\r" && this.buffer[lineEnd] !== "\n") {
        lineEnd += 1;
      }
      if (lineEnd === this.buffer.length) break;

      const terminator = this.buffer[lineEnd];
      if (terminator === "\r" && lineEnd + 1 === this.buffer.length) break;

      const line = this.buffer.slice(cursor, lineEnd);
      cursor = lineEnd + (terminator === "\r" && this.buffer[lineEnd + 1] === "\n" ? 2 : 1);
      const frame = this.processLine(line);
      if (frame !== undefined) frames.push(frame);
    }

    this.buffer = this.buffer.slice(cursor);
    if (this.buffer.length > MAX_SSE_FIELD_CHARS) throw invalidResponse();
    return frames;
  }

  finish(): ParsedSseFrame[] {
    const frames: ParsedSseFrame[] = [];
    if (this.buffer.endsWith("\r")) {
      const frame = this.processLine(this.buffer.slice(0, -1));
      if (frame !== undefined) frames.push(frame);
      this.buffer = "";
    }
    // Per SSE semantics, an unterminated final event is not dispatched. The
    // bounded Go stream always emits a blank line after every complete frame.
    return frames;
  }

  private processLine(line: string): ParsedSseFrame | undefined {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return undefined;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    switch (field) {
      case "data":
        this.dataLines.push(value);
        this.dataChars += value.length;
        if (this.dataChars > MAX_SSE_FIELD_CHARS) throw invalidResponse();
        break;
      case "event":
        this.eventName = value;
        break;
      case "id":
        if (!value.includes("\0")) {
          this.eventId = value;
          this.sawEventId = true;
        }
        break;
      case "retry":
        if (/^[0-9]+$/.test(value)) {
          const parsed = Number(value);
          if (Number.isSafeInteger(parsed)) this.retryMs = parsed;
        }
        break;
      default:
        break;
    }
    return undefined;
  }

  private dispatch(): ParsedSseFrame | undefined {
    const hasData = this.dataLines.length > 0;
    const hasRetry = this.retryMs !== undefined;
    if (!hasData && !hasRetry) {
      this.resetFrame();
      return undefined;
    }

    const frame: ParsedSseFrame = {};
    if (hasData) frame.data = this.dataLines.join("\n");
    if (this.sawEventId) frame.id = this.eventId;
    if (this.eventName !== undefined) frame.event = this.eventName;
    if (this.retryMs !== undefined) frame.retryMs = this.retryMs;
    this.resetFrame();
    return frame;
  }

  private resetFrame(): void {
    this.dataLines = [];
    this.dataChars = 0;
    this.eventName = undefined;
    this.eventId = undefined;
    this.retryMs = undefined;
    this.sawEventId = false;
  }
}

export class MissionControlClient {
  private readonly baseUrl: string;
  private readonly token: string | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly streamControllers = new Set<AbortController>();
  private closed = false;

  constructor(options: MissionControlClientOptions) {
    if (
      !isValidBaseUrl(options.baseUrl) ||
      (options.token !== undefined && !isValidToken(options.token))
    ) {
      throw new MissionControlClientError("invalid_configuration");
    }
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async createMigration(request: CreateMigrationRequest): Promise<MigrationRun> {
    this.assertOpen();
    if (!isCreateMigrationRequest(request)) throw new MissionControlClientError("invalid_request");
    const response = await this.request("/api/v1/migrations", {
      method: "POST",
      body: JSON.stringify(request),
    });
    if (response.status !== 202) throw invalidResponse();
    const run = parseMigrationRun(await readJson(response));
    if (run.portfolioName !== request.portfolioName) throw invalidResponse();
    return run;
  }

  async create(request: CreateMigrationRequest): Promise<MigrationRun> {
    return this.createMigration(request);
  }

  async getMigration(runId: string): Promise<MigrationRun> {
    this.assertOpen();
    assertRunId(runId);
    const response = await this.request(`/api/v1/migrations/${encodeURIComponent(runId)}`, {
      method: "GET",
    });
    if (response.status !== 200) throw invalidResponse();
    const run = parseMigrationRun(await readJson(response));
    if (run.runId !== runId) throw invalidResponse();
    return run;
  }

  async get(runId: string): Promise<MigrationRun> {
    return this.getMigration(runId);
  }

  async approveMigration(runId: string, request: ApprovalRequest): Promise<ApprovalResponse> {
    this.assertOpen();
    assertRunId(runId);
    if (!isApprovalRequest(request)) throw new MissionControlClientError("invalid_request");
    const response = await this.request(`/api/v1/migrations/${encodeURIComponent(runId)}/approval`, {
      method: "POST",
      body: JSON.stringify(request),
    });
    if (response.status !== 200) throw invalidResponse();
    const approval = parseApprovalResponse(await readJson(response));
    if (approval.runId !== runId || approval.planDigest !== request.planDigest || approval.decision !== request.decision) {
      throw invalidResponse();
    }
    return approval;
  }

  async approve(runId: string, request: ApprovalRequest): Promise<ApprovalResponse> {
    return this.approveMigration(runId, request);
  }

  /**
   * Reads the bounded authenticated SSE endpoint forever, reconnecting after
   * clean EOF or retryable transport failures. The cursor advances only after
   * an event has passed the closed wire validation, and that exact SSE id is
   * sent as Last-Event-ID on the next request.
   */
  async *streamEvents(
    runId: string,
    options: StreamEventsOptions = {},
  ): AsyncGenerator<MigrationSseEvent, void, void> {
    this.assertOpen();
    assertRunId(runId);
    if (options.lastEventId !== undefined && !EVENT_ID_PATTERN.test(options.lastEventId)) {
      throw new MissionControlClientError("invalid_request");
    }

    const lifecycle = new AbortController();
    this.streamControllers.add(lifecycle);
    const abortFromCaller = (): void => lifecycle.abort();
    options.signal?.addEventListener("abort", abortFromCaller, { once: true });
    if (options.signal?.aborted === true) lifecycle.abort();

    let lastEventId = options.lastEventId;
    let retryMs = DEFAULT_RETRY_MS;
    notifyConnection(options, "connecting");

    try {
      while (!lifecycle.signal.aborted) {
        let response: Response;
        try {
          response = await this.fetchImpl(this.endpoint(`/api/v1/migrations/${encodeURIComponent(runId)}/events`), {
            method: "GET",
            headers: this.headers("text/event-stream", lastEventId),
            cache: "no-store",
            credentials: "omit",
            redirect: "error",
            referrerPolicy: "no-referrer",
            signal: lifecycle.signal,
          });
        } catch {
          if (lifecycle.signal.aborted) return;
          // A failed transport means the last snapshot is no longer known to
          // be current. Keep the stream stale across every retry until a
          // successful authenticated response proves recovery.
          notifyConnection(options, "stale");
          if (!(await waitForRetry(retryMs, lifecycle.signal))) return;
          continue;
        }

        if (!response.ok) {
          const error = httpError(response.status);
          void response.body?.cancel();
          if (!error.retryable) throw error;
          notifyConnection(options, "stale");
          if (!(await waitForRetry(retryMs, lifecycle.signal))) return;
          continue;
        }
        if (response.status !== 200 || !isEventStreamResponse(response) || response.body === null) {
          void response.body?.cancel();
          throw invalidResponse();
        }

        notifyConnection(options, "connected");
        const parser = new IncrementalSseParser();
        const decoder = new TextDecoder();
        const reader = response.body.getReader();
        let transportFailed = false;
        try {
          while (!lifecycle.signal.aborted) {
            let result: ReadableStreamReadResult<Uint8Array>;
            try {
              result = await reader.read();
            } catch {
              if (lifecycle.signal.aborted) return;
              transportFailed = true;
              break;
            }
            if (result.done) {
              for (const frame of parser.feed(decoder.decode())) {
                const parsed = parseFrame(frame, runId);
                if (parsed.retryMs !== undefined) retryMs = clampRetry(parsed.retryMs);
                if (parsed.event !== undefined) {
                  lastEventId = parsed.event.eventId;
                  yield parsed.event;
                }
              }
              for (const frame of parser.finish()) {
                const parsed = parseFrame(frame, runId);
                if (parsed.retryMs !== undefined) retryMs = clampRetry(parsed.retryMs);
                if (parsed.event !== undefined) {
                  lastEventId = parsed.event.eventId;
                  yield parsed.event;
                }
              }
              break;
            }

            const text = decoder.decode(result.value, { stream: true });
            for (const frame of parser.feed(text)) {
              const parsed = parseFrame(frame, runId);
              if (parsed.retryMs !== undefined) retryMs = clampRetry(parsed.retryMs);
              if (parsed.event !== undefined) {
                lastEventId = parsed.event.eventId;
                yield parsed.event;
              }
            }
          }
        } finally {
          reader.releaseLock();
        }

        if (lifecycle.signal.aborted) return;
        // Clean EOF is the expected boundary of the Go server's bounded SSE
        // replay. The connection remains logically healthy while the client
        // waits to poll again; only an actual read failure makes it stale.
        if (transportFailed) notifyConnection(options, "stale");
        if (!(await waitForRetry(retryMs, lifecycle.signal))) return;
      }
    } finally {
      lifecycle.abort();
      this.streamControllers.delete(lifecycle);
      options.signal?.removeEventListener("abort", abortFromCaller);
      notifyConnection(options, "disconnected");
    }
  }

  /** Permanently closes the client and aborts every active event reader. */
  close(): void {
    if (this.closed) return;
    this.closed = true;
    for (const controller of this.streamControllers) controller.abort();
    this.streamControllers.clear();
  }

  get isClosed(): boolean {
    return this.closed;
  }

  private async request(path: string, init: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(this.endpoint(path), {
        ...init,
        headers: this.headers("application/json"),
        cache: "no-store",
        credentials: "omit",
        redirect: "error",
        referrerPolicy: "no-referrer",
      });
    } catch {
      throw new MissionControlClientError("network_error", undefined, true);
    }
    if (!response.ok) {
      const error = httpError(response.status);
      void response.body?.cancel();
      throw error;
    }
    if (!isJsonResponse(response)) {
      void response.body?.cancel();
      throw invalidResponse();
    }
    return response;
  }

  private headers(accept: string, lastEventId?: string): Headers {
    const headers = new Headers({
      Accept: accept,
    });
    if (this.token !== undefined) headers.set("Authorization", `Bearer ${this.token}`);
    if (accept === "application/json") headers.set("Content-Type", "application/json");
    if (lastEventId !== undefined) headers.set("Last-Event-ID", lastEventId);
    return headers;
  }

  private endpoint(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  private assertOpen(): void {
    if (this.closed) throw new MissionControlClientError("client_closed");
  }
}

interface ParsedFrameResult {
  retryMs?: number;
  event?: MigrationSseEvent;
}

function parseFrame(frame: ParsedSseFrame, runId: string): ParsedFrameResult {
  const result: ParsedFrameResult = {};
  if (frame.retryMs !== undefined) result.retryMs = frame.retryMs;
  if (frame.data === undefined) return result;
  if (frame.id === undefined || frame.event === undefined || !EVENT_ID_PATTERN.test(frame.id)) {
    throw invalidResponse();
  }

  let value: unknown;
  try {
    value = JSON.parse(frame.data) as unknown;
  } catch {
    throw invalidResponse();
  }
  const event = parseMigrationEvent(value);
  if (event.runId !== runId || event.eventId !== frame.id || event.eventType !== frame.event) {
    throw invalidResponse();
  }
  result.event = event;
  return result;
}

function notifyConnection(options: StreamEventsOptions, state: ConnectionState): void {
  options.onConnectionStateChange?.(state);
}

function clampRetry(value: number): number {
  return Math.min(MAX_RETRY_MS, Math.max(MIN_RETRY_MS, value));
}

function waitForRetry(delayMs: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise((resolve) => {
    const timer = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, clampRetry(delayMs));
    const onAbort = (): void => {
      globalThis.clearTimeout(timer);
      resolve(false);
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function isValidBaseUrl(value: string): boolean {
  return value === "" || value.trim() === value;
}

function isValidToken(value: string): boolean {
  if (value.length === 0) return false;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x20 || code >= 0x7f) return false;
  }
  return true;
}

function assertRunId(runId: string): void {
  if (!RUN_ID_PATTERN.test(runId)) throw new MissionControlClientError("invalid_request");
}

function invalidResponse(): MissionControlClientError {
  return new MissionControlClientError("invalid_response");
}

function httpError(status: number): MissionControlClientError {
  if (status === 401 || status === 403) return new MissionControlClientError("unauthorized", status);
  if (status === 404) return new MissionControlClientError("not_found", status);
  if (status === 409) return new MissionControlClientError("conflict", status);
  if (status === 408 || status === 425 || status === 429) {
    return new MissionControlClientError("request_rejected", status, true);
  }
  if (status >= 500) return new MissionControlClientError("server_error", status, true);
  return new MissionControlClientError("request_rejected", status);
}

function isJsonResponse(response: Response): boolean {
  return /^application\/json(?:\s*;\s*charset=(?:utf-8|utf8))?$/i.test(
    response.headers.get("Content-Type") ?? "",
  );
}

function isEventStreamResponse(response: Response): boolean {
  return /^text\/event-stream(?:\s*;\s*charset=(?:utf-8|utf8))?$/i.test(
    response.headers.get("Content-Type") ?? "",
  );
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    throw invalidResponse();
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, required: readonly string[], optional: readonly string[] = []): boolean {
  const allowed = new Set([...required, ...optional]);
  return required.every((key) => Object.hasOwn(value, key)) && Object.keys(value).every((key) => allowed.has(key));
}

function isRunState(value: unknown): value is RunState {
  return typeof value === "string" && RUN_STATES.has(value as RunState);
}

function isSourceId(value: unknown): value is SourceId {
  return value === "jde" || value === "maxdb" || value === "btrieve";
}

function isDateTime(value: unknown): value is string {
  return typeof value === "string" && RFC3339_PATTERN.test(value) && Number.isFinite(Date.parse(value));
}

function isNonNegativeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isOptionalPattern(value: Record<string, unknown>, key: string, pattern: RegExp): boolean {
  return !Object.hasOwn(value, key) || (typeof value[key] === "string" && pattern.test(value[key]));
}

function isSourceDescriptor(value: unknown): value is CreateMigrationRequest["sources"][number] {
  return (
    isObject(value) &&
    hasOnlyKeys(value, ["sourceId", "hostname"]) &&
    isSourceId(value.sourceId) &&
    value.hostname === SOURCE_PRESENTATION[value.sourceId].hostname
  );
}

function isCreateMigrationRequest(value: unknown): value is CreateMigrationRequest {
  if (
    !isObject(value) ||
    !hasOnlyKeys(value, ["schemaVersion", "portfolioName", "sources"], ["requestedBy"]) ||
    value.schemaVersion !== MIGRATION_SCHEMA_VERSION ||
    typeof value.portfolioName !== "string" ||
    value.portfolioName.length > 120 ||
    !PORTFOLIO_NAME_PATTERN.test(value.portfolioName) ||
    !Array.isArray(value.sources) ||
    value.sources.length !== SOURCE_ORDER.length ||
    !value.sources.every(isSourceDescriptor) ||
    !isOptionalPattern(value, "requestedBy", ACTOR_PATTERN)
  ) {
    return false;
  }
  return new Set(value.sources.map((source) => source.sourceId)).size === SOURCE_ORDER.length;
}

function isSourceProgress(value: unknown): value is SourceProgress {
  return (
    isObject(value) &&
    hasOnlyKeys(
      value,
      ["sourceId", "hostname", "state", "recordsRead", "recordsWritten", "recordsRejected"],
      ["planDigest", "failureCode"],
    ) &&
    isSourceId(value.sourceId) &&
    value.hostname === SOURCE_PRESENTATION[value.sourceId].hostname &&
    isRunState(value.state) &&
    isNonNegativeCount(value.recordsRead) &&
    isNonNegativeCount(value.recordsWritten) &&
    isNonNegativeCount(value.recordsRejected) &&
    isOptionalPattern(value, "planDigest", DIGEST_PATTERN) &&
    isOptionalPattern(value, "failureCode", FAILURE_CODE_PATTERN)
  );
}

function parseMigrationRun(value: unknown): MigrationRun {
  if (
    !isObject(value) ||
    !hasOnlyKeys(
      value,
      ["schemaVersion", "runId", "portfolioName", "state", "sources", "createdAt", "updatedAt"],
      ["portfolioPlanDigest", "failureCode"],
    ) ||
    value.schemaVersion !== MIGRATION_SCHEMA_VERSION ||
    typeof value.runId !== "string" ||
    !RUN_ID_PATTERN.test(value.runId) ||
    typeof value.portfolioName !== "string" ||
    value.portfolioName.length < 1 ||
    value.portfolioName.length > 120 ||
    !isRunState(value.state) ||
    !Array.isArray(value.sources) ||
    value.sources.length !== SOURCE_ORDER.length ||
    !value.sources.every(isSourceProgress) ||
    new Set(value.sources.map((source) => source.sourceId)).size !== SOURCE_ORDER.length ||
    !isOptionalPattern(value, "portfolioPlanDigest", DIGEST_PATTERN) ||
    !isOptionalPattern(value, "failureCode", FAILURE_CODE_PATTERN) ||
    !isDateTime(value.createdAt) ||
    !isDateTime(value.updatedAt)
  ) {
    throw invalidResponse();
  }
  return value as unknown as MigrationRun;
}

function isApprovalRequest(value: unknown): value is ApprovalRequest {
  return (
    isObject(value) &&
    hasOnlyKeys(value, ["schemaVersion", "planDigest", "decision", "decidedBy"], ["reason"]) &&
    value.schemaVersion === MIGRATION_SCHEMA_VERSION &&
    typeof value.planDigest === "string" &&
    DIGEST_PATTERN.test(value.planDigest) &&
    (value.decision === "approve" || value.decision === "reject") &&
    typeof value.decidedBy === "string" &&
    value.decidedBy.length <= 120 &&
    ACTOR_PATTERN.test(value.decidedBy) &&
    (!Object.hasOwn(value, "reason") ||
      (typeof value.reason === "string" && value.reason.length >= 1 && value.reason.length <= 500))
  );
}

function parseApprovalResponse(value: unknown): ApprovalResponse {
  if (
    !isObject(value) ||
    !hasOnlyKeys(
      value,
      ["schemaVersion", "approvalId", "runId", "planDigest", "decision", "resultingState", "decidedBy", "decidedAt"],
    ) ||
    value.schemaVersion !== MIGRATION_SCHEMA_VERSION ||
    typeof value.approvalId !== "string" ||
    !APPROVAL_ID_PATTERN.test(value.approvalId) ||
    typeof value.runId !== "string" ||
    !RUN_ID_PATTERN.test(value.runId) ||
    typeof value.planDigest !== "string" ||
    !DIGEST_PATTERN.test(value.planDigest) ||
    (value.decision !== "approve" && value.decision !== "reject") ||
    (value.resultingState !== "approved" && value.resultingState !== "cancelled") ||
    (value.decision === "approve" && value.resultingState !== "approved") ||
    (value.decision === "reject" && value.resultingState !== "cancelled") ||
    typeof value.decidedBy !== "string" ||
    value.decidedBy.length < 1 ||
    value.decidedBy.length > 120 ||
    !isDateTime(value.decidedAt)
  ) {
    throw invalidResponse();
  }
  return value as unknown as ApprovalResponse;
}

function isEvidenceReference(value: unknown): value is EvidenceReference {
  return (
    isObject(value) &&
    hasOnlyKeys(value, ["artifactId", "kind", "digest"]) &&
    typeof value.artifactId === "string" &&
    ARTIFACT_ID_PATTERN.test(value.artifactId) &&
    typeof value.kind === "string" &&
    EVIDENCE_KINDS.has(value.kind as EvidenceKind) &&
    typeof value.digest === "string" &&
    DIGEST_PATTERN.test(value.digest)
  );
}

function parseMigrationEvent(value: unknown): MigrationSseEvent {
  if (
    !isObject(value) ||
    !hasOnlyKeys(
      value,
      ["schemaVersion", "eventId", "runId", "eventType", "timestamp", "summary", "evidenceReferences", "state"],
      ["sourceId"],
    ) ||
    value.schemaVersion !== MIGRATION_SCHEMA_VERSION ||
    typeof value.eventId !== "string" ||
    !EVENT_ID_PATTERN.test(value.eventId) ||
    typeof value.runId !== "string" ||
    !RUN_ID_PATTERN.test(value.runId) ||
    typeof value.eventType !== "string" ||
    !isDateTime(value.timestamp) ||
    typeof value.summary !== "string" ||
    value.summary.length < 1 ||
    value.summary.length > 280 ||
    !Array.isArray(value.evidenceReferences) ||
    value.evidenceReferences.length > 50 ||
    !value.evidenceReferences.every(isEvidenceReference) ||
    !isRunState(value.state)
  ) {
    throw invalidResponse();
  }

  const sourceScoped = SOURCE_EVENT_TYPES.has(value.eventType as SourceEventType);
  const portfolioScoped = PORTFOLIO_EVENT_TYPES.has(value.eventType as PortfolioEventType);
  if (
    (sourceScoped && (!Object.hasOwn(value, "sourceId") || !isSourceId(value.sourceId))) ||
    (portfolioScoped && Object.hasOwn(value, "sourceId")) ||
    (!sourceScoped && !portfolioScoped)
  ) {
    throw invalidResponse();
  }
  return value as unknown as MigrationSseEvent;
}
