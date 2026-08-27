import { containsControlCharacter } from './safety'

export interface FirebasePublicConfig {
  readonly apiKey: string
  readonly authDomain: string
  readonly projectId: string
  readonly appId: string
}

export type FirebaseEnvironment = Readonly<Record<string, string | boolean | undefined>>

export interface FirebaseConfigResult {
  readonly config: FirebasePublicConfig | null
  readonly missing: readonly string[]
}

const CONFIG_KEYS = {
  apiKey: 'VITE_FIREBASE_API_KEY',
  authDomain: 'VITE_FIREBASE_AUTH_DOMAIN',
  projectId: 'VITE_FIREBASE_PROJECT_ID',
  appId: 'VITE_FIREBASE_APP_ID',
} as const

function readSafeValue(environment: FirebaseEnvironment, key: string): string | null {
  const candidate = environment[key]
  if (typeof candidate !== 'string') return null
  const value = candidate.trim()
  if (!value || containsControlCharacter(value)) return null
  return value
}

export function readFirebasePublicConfig(
  environment: FirebaseEnvironment = import.meta.env,
): FirebaseConfigResult {
  const apiKey = readSafeValue(environment, CONFIG_KEYS.apiKey)
  const authDomain = readSafeValue(environment, CONFIG_KEYS.authDomain)
  const projectId = readSafeValue(environment, CONFIG_KEYS.projectId)
  const appId = readSafeValue(environment, CONFIG_KEYS.appId)
  const missing = Object.entries({ apiKey, authDomain, projectId, appId })
    .filter(([, value]) => value === null)
    .map(([name]) => CONFIG_KEYS[name as keyof typeof CONFIG_KEYS])

  if (missing.length > 0 || !apiKey || !authDomain || !projectId || !appId) {
    return { config: null, missing }
  }

  return {
    config: { apiKey, authDomain, projectId, appId },
    missing: [],
  }
}
