import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const LOOPBACK_HOST = '127.0.0.1'
const DEFAULT_API_TARGET = 'http://127.0.0.1:8080'
const STAGE_EXECUTOR_TARGET = 'http://127.0.0.1:4345'
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
  // Identity Platform bearer tokens belong to the browser-facing BFF and are
  // deliberately preserved. Unlike `/api/v1`, this route never injects or
  // substitutes the Mission Control service credential.
  //
  // Exception: when the Go control plane is started with
  // MISSION_CONTROL_LOCAL_DEMO=true it accepts one fixed loopback-only demo
  // identity instead of Identity Platform. Injecting exactly that identity here
  // keeps the credential-free local demo usable. It is a dev-server-only path.
  const localDemo =
    String(process.env.MISSION_CONTROL_LOCAL_DEMO ?? '').trim().toLowerCase() === 'true'
  return {
    target: requireLoopbackTarget(),
    changeOrigin: false,
    ws: false,
    configure: localDemo
      ? (proxy) => {
          proxy.on('proxyReq', (request) => {
            request.setHeader('Authorization', 'Bearer ztm-loopback-demo-v1')
          })
        }
      : undefined,
  }
}

function stageExecutorProxy(): ProxyOptions {
  const token = process.env.KERAUN_STAGE_EXECUTOR_TOKEN
  if (!token) {
    throw new Error('Stage executor authentication is not configured.')
  }
  return {
    target: STAGE_EXECUTOR_TARGET,
    changeOrigin: false,
    ws: false,
    rewrite: (path) => path.replace(/^\/api\/stages/, ''),
    configure: (proxy) => {
      proxy.on('proxyReq', (request) => {
        // The executor credential is held by this dev server and is never
        // compiled into browser JavaScript.
        request.setHeader('Authorization', `Bearer ${token}`)
      })
    },
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
  // The Plugin Factory preflight is a static, synthetic-fixture evidence surface. It
  // has no API dependency, so local reviewers can inspect it without holding
  // a Mission Control service credential or starting the Go backend.
  const localFixtureLab = process.env.MISSION_CONTROL_LOCAL_FIXTURE_LAB === 'true'
  const proxy: Record<string, ProxyOptions> | undefined = command !== 'serve'
    ? undefined
    : {
        ...(process.env.VITE_LOCAL_CARTRIDGE_AGENT === 'true'
          ? { '/api/local-cartridge': localCartridgeAgentProxy() }
          : {}),
        ...(process.env.KERAUN_STAGE_EXECUTOR_TOKEN
          ? { '/api/stages': stageExecutorProxy() }
          : {}),
        // The fixture lab alone needs no Mission Control credential, so those
        // proxies are only mounted when one is actually available.
        ...(localFixtureLab && !process.env.MISSION_CONTROL_API_TOKEN
          ? {}
          : {
              '/api/v1': missionControlProxy(),
              '/api/web/v1': webBffProxy(),
            }),
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
