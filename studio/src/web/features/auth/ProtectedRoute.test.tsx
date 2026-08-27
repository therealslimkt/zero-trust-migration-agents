import { act, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { AuthProvider } from './AuthProvider'
import { readSafeReturnTo } from './navigation'
import { ProtectedRoute } from './ProtectedRoute'
import type { AuthAdapter, AuthUserProfile } from './types'

class FakeAuthAdapter implements AuthAdapter {
  private onUser: ((user: AuthUserProfile | null) => void) | null = null

  subscribe(onUser: (user: AuthUserProfile | null) => void) {
    this.onUser = onUser
    return vi.fn()
  }

  emit(user: AuthUserProfile | null) {
    this.onUser?.(user)
  }

  async signInWithGoogle() {}
  async signOut() {}
  async getCurrentUserIdToken() { return 'token' }
}

function SignInProbe() {
  const location = useLocation()
  const state = location.state as { returnTo?: string } | null
  return <p>Sign in return: {state?.returnTo ?? 'none'}</p>
}

describe('ProtectedRoute', () => {
  it('preserves intended path, query, and hash when redirecting an anonymous user', () => {
    const adapter = new FakeAuthAdapter()
    render(
      <AuthProvider adapter={adapter}>
        <MemoryRouter initialEntries={['/runs/run-7?pane=evidence#digest']}>
          <Routes>
            <Route path="/sign-in" element={<SignInProbe />} />
            <Route
              path="/runs/:runId"
              element={<ProtectedRoute initializingFallback={<p>Loading auth</p>}><p>Protected run</p></ProtectedRoute>}
            />
          </Routes>
        </MemoryRouter>
      </AuthProvider>,
    )

    expect(screen.getByText('Loading auth')).toBeVisible()
    act(() => adapter.emit(null))
    expect(screen.getByText('Sign in return: /runs/run-7?pane=evidence#digest')).toBeVisible()
  })

  it('renders protected content only for an authenticated user', () => {
    const adapter = new FakeAuthAdapter()
    render(
      <AuthProvider adapter={adapter}>
        <MemoryRouter initialEntries={['/dashboard']}>
          <ProtectedRoute initializingFallback={<p>Loading auth</p>}>
            <p>Protected dashboard</p>
          </ProtectedRoute>
        </MemoryRouter>
      </AuthProvider>,
    )

    act(() => adapter.emit({
      uid: 'user-1',
      displayName: 'Operator',
      email: 'operator@example.com',
      emailVerified: true,
      photoURL: null,
      providerIds: ['google.com'],
    }))

    expect(screen.getByText('Protected dashboard')).toBeVisible()
  })

  it('does not redirect-loop if the sign-in route is accidentally protected', () => {
    const adapter = new FakeAuthAdapter()
    render(
      <AuthProvider adapter={adapter}>
        <MemoryRouter initialEntries={['/sign-in']}>
          <ProtectedRoute anonymousFallback={<p>Sign-in unavailable</p>}>
            <p>Protected content</p>
          </ProtectedRoute>
        </MemoryRouter>
      </AuthProvider>,
    )

    act(() => adapter.emit(null))
    expect(screen.getByText('Sign-in unavailable')).toBeVisible()
  })
})

describe('readSafeReturnTo', () => {
  it('accepts only same-origin relative navigation state', () => {
    expect(readSafeReturnTo({ returnTo: '/runs/7?pane=plan#step' })).toBe('/runs/7?pane=plan#step')
    expect(readSafeReturnTo({ returnTo: '//attacker.example/path' })).toBe('/dashboard')
    expect(readSafeReturnTo({ returnTo: 'https://attacker.example/path' })).toBe('/dashboard')
    expect(readSafeReturnTo({ returnTo: '/safe\\attacker.example' })).toBe('/dashboard')
    expect(readSafeReturnTo(null, '/')).toBe('/')
  })
})
