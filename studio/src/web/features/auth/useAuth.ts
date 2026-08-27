import { useContext } from 'react'

import { AuthContext } from './context'
import type { AuthContextValue } from './types'

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within an AuthProvider.')
  return context
}
/** Stable callback for BFF clients that need a current bearer token per call. */
export function useBffIdTokenProvider(): (forceRefresh?: boolean) => Promise<string> {
  return useAuth().getIdToken
}
