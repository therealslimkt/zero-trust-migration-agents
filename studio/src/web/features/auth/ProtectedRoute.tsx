import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'

import type { AuthReturnState } from './navigation'
import { useAuth } from './useAuth'

export interface ProtectedRouteProps {
  readonly children: ReactNode
  readonly signInPath?: string
  readonly initializingFallback?: ReactNode
  readonly anonymousFallback?: ReactNode
  readonly unconfiguredFallback?: ReactNode
  readonly errorFallback?: ReactNode
}

function locationPath(location: Pick<Location, 'pathname' | 'search' | 'hash'>): string {
  return `${location.pathname}${location.search}${location.hash}`
}

export function ProtectedRoute({
  children,
  signInPath = '/login',
  initializingFallback = null,
  anonymousFallback = null,
  unconfiguredFallback = null,
  errorFallback = null,
}: ProtectedRouteProps) {
  const auth = useAuth()
  const location = useLocation()

  if (auth.status === 'initializing') return initializingFallback
  if (auth.status === 'unconfigured') return unconfiguredFallback
  if (auth.status === 'error') return errorFallback
  if (auth.status === 'authenticated') return children

  // If a router accidentally protects its own sign-in route, render the
  // anonymous fallback instead of repeatedly replacing the same location.
  if (location.pathname === signInPath) return anonymousFallback

  const state: AuthReturnState = { returnTo: locationPath(location) }
  return <Navigate to={signInPath} replace state={state} />
}
