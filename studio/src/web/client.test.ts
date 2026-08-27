import assert from "node:assert/strict";
import test from "node:test";

import { LiveWebClient, RecordedDemoClient } from "./client.js";
import { WEB_SCHEMA_VERSION } from "./contracts.generated.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

test("recorded demo client exposes only public read methods", () => {
  const methods = Object.getOwnPropertyNames(RecordedDemoClient.prototype).sort();
  assert.deepEqual(methods, ["constructor", "get", "getByDigest", "list"]);
});

test("recorded demo client uses the separate /api/web/v1 prefix", async () => {
  const calls: string[] = [];
  const fetchImpl: typeof fetch = async (input) => {
    calls.push(String(input));
    return jsonResponse({ schemaVersion: WEB_SCHEMA_VERSION, demos: [] });
  };
  await new RecordedDemoClient({ baseUrl: "https://example.test/", fetchImpl }).list();
  assert.deepEqual(calls, ["https://example.test/api/web/v1/demos"]);
});

test("live event fetch sends verified identity and resumable event header", async () => {
  let request: Request | undefined;
  const fetchImpl: typeof fetch = async (input, init) => {
    const target = String(input);
    request = new Request(target.startsWith("/") ? `http://localhost${target}` : target, init);
    return new Response("", { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
  const client = new LiveWebClient(async () => "verified-id-token", { fetchImpl });
  const response = await client.openRunEvents("mig_recordedDemo001", "evt_migrationcreated01");
  assert.equal(response.status, 200);
  assert.equal(request?.url, "http://localhost/api/web/v1/runs/mig_recordedDemo001/events");
  assert.equal(request?.headers.get("Authorization"), "Bearer verified-id-token");
  assert.equal(request?.headers.get("Last-Event-ID"), "evt_migrationcreated01");
});
