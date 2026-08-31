import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const LOOPBACK_HOST = '127.0.0.1'
const DEFAULT_API_TARGET = 'http://127.0.0.1:8080'
const LOCAL_CARTRIDGE_AGENT_TARGET = 'http://127.0.0.1:4344'

function requireProxyToken(): string {
  const token = process.env.MISSION_CONTROL_API_TOKEN
  if (!token) throw new Error('Mission Control proxy authentication is not configured.')
  for (let index = 0; index < token.length; index += 1) {
    const code = token.charCodeAt(index)
    if (code <= 0x20 || code >= 0x7f) {
      throw new Error('Mission Control proxy authentication is invalid.')
    }
  }
  return token
}

function requireLoopbackTarget(): string {
  const configured = process.env.MISSION_CONTROL_PROXY_TARGET?.trim() || DEFAULT_API_TARGET
  let target: URL
  try {
    target = new URL(configured)
  } catch {
    throw new Error('Mission Control proxy target is invalid.')
  }
  const loopback = target.hostname === '127.0.0.1' || target.hostname === '[::1]' || target.hostname === 'localhost'
  if (
    target.protocol !== 'http:' ||
    !loopback ||
    target.username !== '' ||
    target.password !== '' ||
    target.pathname !== '/' ||
    target.search !== '' ||
    target.hash !== ''
  ) {
    throw new Error('Mission Control proxy target must be an uncredentialed loopback HTTP origin.')
  }
  return target.origin
}

function missionControlProxy(): ProxyOptions {
  const token = requireProxyToken()
  return {
    target: requireLoopbackTarget(),
    changeOrigin: false,
    ws: false,
    configure(proxy) {
      proxy.on('proxyReq', (request) => {
        // The browser never supplies the upstream credential. Remove any
        // caller-provided value before setting the one server-held token so
        // the Go handler always receives exactly one Authorization header.
        request.removeHeader('authorization')
        request.setHeader('Authorization', `Bearer ${token}`)
      })
    },
  }
}

function webBffProxy(): ProxyOptions {
  return {
    target: requireLoopbackTarget(),
    changeOrigin: false,
    ws: false,
    // Identity Platform bearer tokens belong to the browser-facing BFF and
    // are deliberately preserved. Unlike `/api/v1`, this route never injects
    // or substitutes the Mission Control service credential.
  }
}

function localCartridgeAgentProxy(): ProxyOptions {
  const token = process.env.KERAUN_LOCAL_CARTRIDGE_AGENT_TOKEN
  if (!token || token.length < 32 || /[^\x21-\x7e]/.test(token)) {
    throw new Error('Local cartridge agent authentication is not configured.')
  }
  return {
    target: LOCAL_CARTRIDGE_AGENT_TARGET,
    changeOrigin: false,
    ws: false,
    rewrite: (path) => path.replace(/^\/api\/local-cartridge/, ''),
    configure(proxy) {
      proxy.on('proxyReq', (request) => {
        request.removeHeader('authorization')
        request.setHeader('Authorization', `Bearer ${token}`)
      })
    },
  }
}

export default defineConfig(({ command }) => {
  // The M4 cartridge lab is a static, synthetic-fixture evidence surface. It
  // has no API dependency, so local reviewers can inspect it without holding
  // a Mission Control service credential or starting the Go backend.
  const localFixtureLab = process.env.MISSION_CONTROL_LOCAL_FIXTURE_LAB === 'true'
  const proxy: Record<string, ProxyOptions> | undefined = command !== 'serve'
    ? undefined
    : localFixtureLab
      ? process.env.VITE_LOCAL_CARTRIDGE_AGENT === 'true'
        ? { '/api/local-cartridge': localCartridgeAgentProxy() }
        : undefined
      : {
          '/api/v1': missionControlProxy(),
          '/api/web/v1': webBffProxy(),
        }
  const localServer = {
    host: LOOPBACK_HOST,
    strictPort: !localFixtureLab,
    allowedHosts: ['127.0.0.1', 'localhost'],
    cors: false,
    proxy,
  }

  return {
    plugins: [react()],
    server: localServer,
    preview: localServer,
  }
})
