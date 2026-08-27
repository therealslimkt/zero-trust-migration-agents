export const AUTH_STATUSES = [
  'initializing',
  'anonymous',
  'authenticated',
  'error',
  'unconfigured',
] as const

export type AuthStatus = (typeof AUTH_STATUSES)[number]

/**
 * Authenticated display data sourced from Firebase Auth, not from route state,
 * form fields, or API callers. `emailVerified` remains explicit so the UI does
 * not imply that an unverified address is verified.
 */
export interface AuthUserProfile {
  readonly uid: string
  readonly displayName: string | null
  readonly email: string | null
  readonly emailVerified: boolean
  readonly photoURL: string | null
  readonly providerIds: readonly string[]
}
export interface AuthAdapter {
  subscribe(
    onUser: (user: AuthUserProfile | null) => void,
    onError: (error: unknown) => void,
  ): () => void
  signInWithGoogle(): Promise<void>
  signOut(): Promise<void>
  getCurrentUserIdToken(forceRefresh?: boolean): Promise<string>
}

export type AuthOperation = 'sign-in' | 'sign-out' | null

export interface AuthContextValue {
  readonly status: AuthStatus
  readonly user: AuthUserProfile | null
  readonly error: Error | null
  readonly operation: AuthOperation
  readonly isAuthenticated: boolean
  readonly isConfigured: boolean
  signInWithGoogle(): Promise<void>
  signOut(): Promise<void>
  /** Returns a fresh SDK-managed token without caching it in app state/storage. */
  getIdToken(forceRefresh?: boolean): Promise<string>
}

export class AuthUnavailableError extends Error {
  readonly code: 'auth/unconfigured' | 'auth/anonymous' | 'auth/initializing'

  constructor(code: AuthUnavailableError['code'], message: string) {
    super(message)
    this.name = 'AuthUnavailableError'
    this.code = code
  }
}
