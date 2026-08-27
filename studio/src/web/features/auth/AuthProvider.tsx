import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'

import { readFirebasePublicConfig } from './config'
import { AuthContext } from './context'
import type { AuthAdapter, AuthContextValue, AuthOperation, AuthStatus, AuthUserProfile } from './types'
import { AuthUnavailableError } from './types'

interface AuthSnapshot {
  readonly status: AuthStatus
  readonly user: AuthUserProfile | null
  readonly error: Error | null
}

export interface AuthProviderProps {
  readonly children: ReactNode
  /** Dependency-injection seam for deterministic tests and non-Firebase hosts. */
  readonly adapter?: AuthAdapter
}

const INITIAL_SNAPSHOT: AuthSnapshot = {
  status: 'initializing',
  user: null,
  error: null,
}

function normalizeError(error: unknown): Error {
  return error instanceof Error ? error : new Error('Authentication failed.')
}

export function AuthProvider({ children, adapter: injectedAdapter }: AuthProviderProps) {
  const configResult = useMemo(() => readFirebasePublicConfig(), [])
  const [snapshot, setSnapshot] = useState<AuthSnapshot>(
    injectedAdapter || configResult.config ? INITIAL_SNAPSHOT : {
      status: 'unconfigured',
      user: null,
      error: null,
    },
  )
  const [operation, setOperation] = useState<AuthOperation>(null)
  const [operationError, setOperationError] = useState<Error | null>(null)
  const adapterRef = useRef<AuthAdapter | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    let active = true
    let unsubscribe: (() => void) | undefined

    const attach = (adapter: AuthAdapter) => {
      if (!active) return
      adapterRef.current = adapter
      unsubscribe = adapter.subscribe(
        (user) => {
          if (!active) return
          setOperationError(null)
          setSnapshot({
            status: user ? 'authenticated' : 'anonymous',
            user,
            error: null,
          })
        },
        (error) => {
          if (!active) return
          setSnapshot({ status: 'error', user: null, error: normalizeError(error) })
        },
      )
    }

    if (injectedAdapter) {
      attach(injectedAdapter)
    } else if (!configResult.config) {
      adapterRef.current = null
    } else {
      void import('./firebaseAdapter')
        .then(({ createFirebaseAuthAdapter }) => {
          if (active) attach(createFirebaseAuthAdapter(configResult.config!))
        })
        .catch((error: unknown) => {
          if (!active) return
          setSnapshot({ status: 'error', user: null, error: normalizeError(error) })
        })
    }

    return () => {
      active = false
      mountedRef.current = false
      adapterRef.current = null
      unsubscribe?.()
    }
  }, [configResult.config, injectedAdapter])

  const runOperation = useCallback(async (kind: Exclude<AuthOperation, null>, action: (adapter: AuthAdapter) => Promise<void>) => {
    const adapter = adapterRef.current
    if (!adapter) {
      const code = snapshot.status === 'unconfigured' ? 'auth/unconfigured' : 'auth/initializing'
      throw new AuthUnavailableError(code, 'Authentication is not available.')
    }

    setOperation(kind)
    setOperationError(null)
    try {
      await action(adapter)
    } catch (error) {
      const normalized = normalizeError(error)
      if (mountedRef.current) setOperationError(normalized)
      throw normalized
    } finally {
      if (mountedRef.current) setOperation(null)
    }
  }, [snapshot.status])

  const signInWithGoogle = useCallback(
    () => runOperation('sign-in', (adapter) => adapter.signInWithGoogle()),
    [runOperation],
  )

  const signOutUser = useCallback(
    () => runOperation('sign-out', (adapter) => adapter.signOut()),
    [runOperation],
  )

  const getIdToken = useCallback(async (forceRefresh = false) => {
    if (snapshot.status !== 'authenticated') {
      const code = snapshot.status === 'unconfigured'
        ? 'auth/unconfigured'
        : snapshot.status === 'initializing'
          ? 'auth/initializing'
          : 'auth/anonymous'
      throw new AuthUnavailableError(code, 'An authenticated user is required.')
    }
    const adapter = adapterRef.current
    if (!adapter) {
      throw new AuthUnavailableError('auth/initializing', 'Authentication is not ready.')
    }
    return adapter.getCurrentUserIdToken(forceRefresh)
  }, [snapshot.status])

  const value = useMemo<AuthContextValue>(() => ({
    status: snapshot.status,
    user: snapshot.user,
    error: operationError ?? snapshot.error,
    operation,
    isAuthenticated: snapshot.status === 'authenticated',
    isConfigured: snapshot.status !== 'unconfigured',
    signInWithGoogle,
    signOut: signOutUser,
    getIdToken,
  }), [getIdToken, operation, operationError, signInWithGoogle, signOutUser, snapshot])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
