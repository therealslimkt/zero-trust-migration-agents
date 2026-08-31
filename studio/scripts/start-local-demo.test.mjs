import assert from 'node:assert/strict'
import { access, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import test from 'node:test'

import { findLoopbackPort, prepareLocalDemoState } from './start-local-demo.mjs'

test('the default backend port is loopback-allocated rather than hard-coded', async () => {
  const port = await findLoopbackPort()
  assert.match(port, /^[1-9][0-9]{1,4}$/)
})

test('an occupied preferred frontend port falls back to a different loopback port', async (t) => {
  const occupied = createServer()
  await new Promise((resolve, reject) => {
    occupied.once('error', reject)
    occupied.listen({ host: '127.0.0.1', port: 0 }, resolve)
  })
  t.after(() => new Promise((resolve, reject) => occupied.close((error) => error ? reject(error) : resolve())))

  const address = occupied.address()
  assert.ok(address && typeof address !== 'string')
  const port = await findLoopbackPort(address.port)

  assert.match(port, /^[1-9][0-9]{1,4}$/)
  assert.notEqual(port, String(address.port))
})

test('no configured state allocates a fresh temporary control-plane path', async (t) => {
  const prepared = await prepareLocalDemoState(undefined, {})
  t.after(() => rm(dirname(prepared.statePath), { force: true, recursive: true }))

  assert.equal(prepared.temporary, true)
  assert.equal(prepared.statePath.endsWith('/control-plane.json'), true)
  assert.deepEqual(prepared.runIds, [])
  await assert.rejects(access(prepared.statePath), { code: 'ENOENT' })
})

test('an explicit state path remains authoritative and supplies existing run IDs', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'mission-control-explicit-demo-test-'))
  t.after(() => rm(directory, { force: true, recursive: true }))
  const statePath = join(directory, 'control-plane.json')
  await writeFile(statePath, JSON.stringify({
    runs: [
      { runId: 'run_existing_one' },
      { ignored: true },
      { runId: 'run_existing_two' },
    ],
  }))

  const prepared = await prepareLocalDemoState(statePath, {})

  assert.equal(prepared.temporary, false)
  assert.equal(prepared.statePath, statePath)
  assert.deepEqual(prepared.runIds, ['run_existing_one', 'run_existing_two'])
})

test('a configured but unreadable state fails instead of silently replacing it', async () => {
  await assert.rejects(
    prepareLocalDemoState('/definitely/not/a/mission-control-state.json', {}),
    /Local demo state could not be read/,
  )
})
