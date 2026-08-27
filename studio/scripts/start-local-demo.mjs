import { randomBytes } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { spawn } from 'node:child_process'

function option(name) {
  const index = process.argv.indexOf(name)
  return index >= 0 ? process.argv[index + 1] : undefined
}

const stateArgument = option('--state') || process.env.MISSION_CONTROL_STATE_PATH
if (!stateArgument) {
  console.error('Usage: npm run dev:demo -- --state /absolute/path/to/control-plane.json')
  process.exit(2)
}

const statePath = resolve(stateArgument)
let snapshot
try {
  snapshot = JSON.parse(await readFile(statePath, 'utf8'))
} catch {
  console.error(`Local demo state could not be read: ${statePath}`)
  process.exit(2)
}

const runIds = Array.isArray(snapshot?.runs)
  ? snapshot.runs.map((run) => run?.runId).filter((runId) => typeof runId === 'string')
  : []
const apiToken = process.env.MISSION_CONTROL_API_TOKEN || randomBytes(32).toString('hex')
const webStatePath = process.env.MISSION_CONTROL_WEB_STATE_PATH || `${statePath}.web-demo.json`
const port = option('--port') || '5173'
const studioDirectory = resolve(import.meta.dirname, '..')
const repositoryDirectory = resolve(studioDirectory, '..')

const environment = {
  ...process.env,
  MISSION_CONTROL_STATE_PATH: statePath,
  MISSION_CONTROL_API_TOKEN: apiToken,
  MISSION_CONTROL_WEB_STATE_PATH: webStatePath,
  MISSION_CONTROL_LOCAL_DEMO: 'true',
  MISSION_CONTROL_LOCAL_DEMO_RUN_IDS: runIds.join(','),
  VITE_LOCAL_DEMO: 'true',
}
delete environment.MISSION_CONTROL_FIREBASE_PROJECT_ID

console.log(`Local demo: ${runIds.length} durable run${runIds.length === 1 ? '' : 's'} from ${statePath}`)
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
    if (!closing) {
      console.error(`${name} stopped unexpectedly (${signal || code}).`)
      close()
      process.exitCode = code || 1
    }
  })
}

await new Promise(() => {})
