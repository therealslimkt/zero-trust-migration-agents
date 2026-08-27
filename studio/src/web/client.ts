import type {
  CloudSetupRequest,
  CloudSetupResponse,
  CloudConnectionResponse,
  CloudVerifyRequest,
  CloudVerifyResponse,
  CreateLiveRunRequest,
  DemoManifest,
  DriverApprovalRequest,
  DriverApprovalResponse,
  DriverResearchRequest,
  DriverResearchAccepted,
  DriverResearchStatusResponse,
  ListDemosResponse,
  ListLiveRunsResponse,
  LiveApprovalRequest,
  LiveApprovalResponse,
  LiveRunSummary,
  LiveSourceResponse,
  ProblemDetails,
  PublishDemoRequest,
  PublishDemoResponse,
  SessionResponse,
  SourceId,
} from "./contracts.generated.js";

export type IdentityTokenProvider = () => Promise<string>;

export class WebApiError extends Error {
  readonly status: number;
  readonly problem?: ProblemDetails;

  constructor(status: number, message: string, problem?: ProblemDetails) {
    super(message);
    this.name = "WebApiError";
    this.status = status;
    this.problem = problem;
  }
}

interface ClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

function cleanBaseUrl(value: string): string {
  return value === "/" ? "" : value.replace(/\/$/, "");
}

function segment(value: string): string {
  return encodeURIComponent(value);
}

async function decode<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;
  let problem: ProblemDetails | undefined;
  if (response.headers.get("content-type")?.includes("application/problem+json")) {
    problem = (await response.json()) as ProblemDetails;
  }
  throw new WebApiError(response.status, problem?.title ?? "The web service could not complete the request.", problem);
}

/** Read-only public replay client. It intentionally has no mutation methods. */
export class RecordedDemoClient {
  readonly #baseUrl: string;
  readonly #fetch: typeof fetch;

  constructor(options: ClientOptions = {}) {
    this.#baseUrl = cleanBaseUrl(options.baseUrl ?? "");
    this.#fetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async list(): Promise<ListDemosResponse> {
    return decode(await this.#fetch(`${this.#baseUrl}/api/web/v1/demos`, { credentials: "same-origin" }));
  }

  async get(demoId: string): Promise<DemoManifest> {
    return decode(await this.#fetch(`${this.#baseUrl}/api/web/v1/demos/${segment(demoId)}`, { credentials: "same-origin" }));
  }

  async getByDigest(bundleDigest: string): Promise<DemoManifest> {
    return decode(await this.#fetch(`${this.#baseUrl}/api/web/v1/demo-bundles/${segment(bundleDigest)}`, { credentials: "same-origin" }));
  }
}

/** Authenticated live client. Identity tokens are requested immediately before each call. */
export class LiveWebClient {
  readonly #baseUrl: string;
  readonly #fetch: typeof fetch;
  readonly #token: IdentityTokenProvider;

  constructor(tokenProvider: IdentityTokenProvider, options: ClientOptions = {}) {
    this.#token = tokenProvider;
    this.#baseUrl = cleanBaseUrl(options.baseUrl ?? "");
    this.#fetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async #response(path: string, init: RequestInit = {}): Promise<Response> {
    const token = await this.#token();
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${token}`);
    if (init.body !== undefined) headers.set("Content-Type", "application/json");
    return this.#fetch(`${this.#baseUrl}${path}`, { ...init, headers, credentials: "same-origin" });
  }

  async #request<T>(path: string, init: RequestInit = {}): Promise<T> {
    return decode(await this.#response(path, init));
  }

  getSession(): Promise<SessionResponse> {
    return this.#request("/api/web/v1/session");
  }

  listRuns(): Promise<ListLiveRunsResponse> {
    return this.#request("/api/web/v1/runs");
  }

  getRun(runId: string): Promise<LiveRunSummary> {
    return this.#request(`/api/web/v1/runs/${segment(runId)}`);
  }

  createRun(request: CreateLiveRunRequest): Promise<LiveRunSummary> {
    return this.#request("/api/web/v1/runs", { method: "POST", body: JSON.stringify(request) });
  }

  getSource(runId: string, sourceId: SourceId): Promise<LiveSourceResponse> {
    return this.#request(`/api/web/v1/runs/${segment(runId)}/sources/${segment(sourceId)}`);
  }

  async openRunEvents(runId: string, lastEventId?: string, signal?: AbortSignal): Promise<Response> {
    const headers = new Headers({ Accept: "text/event-stream" });
    if (lastEventId !== undefined) headers.set("Last-Event-ID", lastEventId);
    const response = await this.#response(`/api/web/v1/runs/${segment(runId)}/events`, { headers, signal });
    if (!response.ok) await decode<never>(response);
    return response;
  }

  decideRun(runId: string, request: LiveApprovalRequest): Promise<LiveApprovalResponse> {
    return this.#request(`/api/web/v1/runs/${segment(runId)}/approval`, { method: "POST", body: JSON.stringify(request) });
  }

  createCloudSetup(request: CloudSetupRequest): Promise<CloudSetupResponse> {
    return this.#request("/api/web/v1/cloud/connection/setup", { method: "POST", body: JSON.stringify(request) });
  }

  verifyCloudSetup(request: CloudVerifyRequest): Promise<CloudVerifyResponse> {
    return this.#request("/api/web/v1/cloud/connection/verify", { method: "POST", body: JSON.stringify(request) });
  }

  getCloudConnection(): Promise<CloudConnectionResponse> {
    return this.#request("/api/web/v1/cloud/connection");
  }

  researchDrivers(request: DriverResearchRequest): Promise<DriverResearchAccepted> {
    return this.#request("/api/web/v1/drivers/research", { method: "POST", body: JSON.stringify(request) });
  }

  getDriverResearch(researchId: string): Promise<DriverResearchStatusResponse> {
    return this.#request(`/api/web/v1/drivers/research/${segment(researchId)}`);
  }

  approveDriver(researchId: string, request: DriverApprovalRequest): Promise<DriverApprovalResponse> {
    return this.#request(`/api/web/v1/drivers/research/${segment(researchId)}/approval`, { method: "POST", body: JSON.stringify(request) });
  }

  publishDemo(request: PublishDemoRequest): Promise<PublishDemoResponse> {
    return this.#request("/api/web/v1/demo-publications", { method: "POST", body: JSON.stringify(request) });
  }
}
