import { expect, test } from 'vitest'

import { LiveWebClient, RecordedDemoClient } from './client.js'
import { WEB_SCHEMA_VERSION } from './contracts.generated.js'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

test('recorded demo client exposes only public read methods', () => {
  const methods = Object.getOwnPropertyNames(RecordedDemoClient.prototype).sort()
  expect(methods).toEqual(['constructor', 'get', 'getByDigest', 'list'])
})

test('recorded demo client uses the separate /api/web/v1 prefix', async () => {
  const calls: string[] = []
  const fetchImpl: typeof fetch = async (input) => {
    calls.push(String(input))
    return jsonResponse({ schemaVersion: WEB_SCHEMA_VERSION, demos: [] })
  }
  await new RecordedDemoClient({ baseUrl: 'https://example.test/', fetchImpl }).list()
  expect(calls).toEqual(['https://example.test/api/web/v1/demos'])
})

test('live event fetch sends verified identity and resumable event header', async () => {
  let request: Request | undefined
  const fetchImpl: typeof fetch = async (input, init) => {
    const target = String(input)
    request = new Request(target.startsWith('/') ? `http://localhost${target}` : target, init)
    return new Response('', { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  }
  const client = new LiveWebClient(async () => 'verified-id-token', { fetchImpl })
  const response = await client.openRunEvents('mig_recordedDemo001', 'evt_migrationcreated01')
  expect(response.status).toBe(200)
  expect(request?.url).toBe('http://localhost/api/web/v1/runs/mig_recordedDemo001/events')
  expect(request?.headers.get('Authorization')).toBe('Bearer verified-id-token')
  expect(request?.headers.get('Last-Event-ID')).toBe('evt_migrationcreated01')
})
