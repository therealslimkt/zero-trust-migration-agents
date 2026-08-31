import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { mkdtemp, readFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

function option(name, argv = process.argv) {
  const index = argv.indexOf(name)
  if (index < 0) return undefined

  const value = argv[index + 1]
  if (!value || value.startsWith('--')) {
    throw new Error(`${name} requires a value`)
  }
  return value
}

function runIdsFromSnapshot(snapshot) {
  return Array.isArray(snapshot?.runs)
    ? snapshot.runs.map((run) => run?.runId).filter((runId) => typeof runId === 'string')
    : []
}

export async function prepareLocalDemoState(stateArgument, environment = process.env) {
  const configuredState = stateArgument || environment.MISSION_CONTROL_STATE_PATH
  if (!configuredState) {
    const directory = await mkdtemp(join(tmpdir(), 'mission-control-local-demo-'))
    return {
      runIds: [],
      statePath: join(directory, 'control-plane.json'),
      temporary: true,
    }
  }

  const statePath = resolve(configuredState)
  let snapshot
  try {
    snapshot = JSON.parse(await readFile(statePath, 'utf8'))
  } catch {
    throw new Error(`Local demo state could not be read: ${statePath}`)
  }
  return {
    runIds: runIdsFromSnapshot(snapshot),
    statePath,
    temporary: false,
  }
}

/** Select a currently unused loopback port for the disposable local backend. */
export async function findLoopbackPort() {
  const server = createServer()
  await new Promise((resolvePromise, reject) => {
    server.once('error', reject)
    server.listen({ host: '127.0.0.1', port: 0 }, resolvePromise)
  })
  const address = server.address()
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()))
  if (!address || typeof address === 'string' || !Number.isInteger(address.port) || address.port < 1) {
    throw new Error('Local demo could not reserve a loopback backend port')
  }
  return String(address.port)
}

export async function main(argv = process.argv, processEnvironment = process.env) {
  let prepared
  let port
  let backendPort
  try {
    prepared = await prepareLocalDemoState(option('--state', argv), processEnvironment)
    port = option('--port', argv) || '5173'
    backendPort = processEnvironment.MISSION_CONTROL_LOCAL_DEMO_PORT?.trim() || await findLoopbackPort()
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 2
    return
  }

  const { runIds, statePath, temporary } = prepared
  const apiToken = processEnvironment.MISSION_CONTROL_API_TOKEN || randomBytes(32).toString('hex')
  const webStatePath = processEnvironment.MISSION_CONTROL_WEB_STATE_PATH || `${statePath}.web-demo.json`
  const studioDirectory = resolve(import.meta.dirname, '..')
  const repositoryDirectory = resolve(studioDirectory, '..')

  const environment = {
    ...processEnvironment,
    MISSION_CONTROL_STATE_PATH: statePath,
    MISSION_CONTROL_API_TOKEN: apiToken,
    MISSION_CONTROL_WEB_STATE_PATH: webStatePath,
    MISSION_CONTROL_LOCAL_DEMO: 'true',
    MISSION_CONTROL_LOCAL_DEMO_PORT: backendPort,
    MISSION_CONTROL_LOCAL_DEMO_RUN_IDS: runIds.join(','),
    MISSION_CONTROL_PROXY_TARGET: `http://127.0.0.1:${backendPort}`,
    VITE_LOCAL_DEMO: 'true',
  }
  delete environment.MISSION_CONTROL_FIREBASE_PROJECT_ID

  console.log(`Local demo state: ${statePath}${temporary ? ' (temporary)' : ''}`)
  console.log(`Local demo backend: http://127.0.0.1:${backendPort}`)
  console.log(`Local demo: ${runIds.length} existing durable run${runIds.length === 1 ? '' : 's'}`)
  console.log(`Local demo UI: http://127.0.0.1:${port}`)

  const backend = spawn('go', ['run', '.'], {
    cwd: resolve(repositoryDirectory, 'studio-backend'),
    env: environment,
    stdio: 'inherit',
  })
  const frontend = spawn('npm', ['run', 'dev', '--', '--host', '127.0.0.1', '--port', port], {
    cwd: studioDirectory,
    env: environment,
    stdio: 'inherit',
  })

  let closing = false
  let childrenStopped = 0
  let finish
  const childrenFinished = new Promise((resolveFinished) => {
    finish = resolveFinished
  })
  function close(signal = 'SIGTERM') {
    if (closing) return
    closing = true
    backend.kill(signal)
    frontend.kill(signal)
  }

  for (const signal of ['SIGINT', 'SIGTERM']) {
    process.on(signal, () => close(signal))
  }

  for (const [name, child] of [['backend', backend], ['frontend', frontend]]) {
    child.on('exit', (code, signal) => {
      childrenStopped += 1
      if (!closing) {
        console.error(`${name} stopped unexpectedly (${signal || code}).`)
        close()
        process.exitCode = code || 1
      }
      if (childrenStopped === 2) finish()
    })
  }

  await childrenFinished
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : ''
if (import.meta.url === invokedPath) {
  await main()
}
