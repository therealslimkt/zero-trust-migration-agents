import { defineConfig } from 'vite'
import type { ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'

const LOOPBACK_HOST = '127.0.0.1'
const DEFAULT_API_TARGET = 'http://127.0.0.1:8080'

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

export default defineConfig(({ command }) => {
  const proxy = command === 'serve' ? { '/api/v1': missionControlProxy() } : undefined
  const localServer = {
    host: LOOPBACK_HOST,
    strictPort: true,
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
