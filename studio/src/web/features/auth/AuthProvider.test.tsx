import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { AuthProvider } from './AuthProvider'
import type { AuthAdapter, AuthUserProfile } from './types'
import { useAuth } from './useAuth'

const VERIFIED_USER: AuthUserProfile = {
  uid: 'firebase-user-123',
  displayName: 'Demo Operator',
  email: 'operator@example.com',
  emailVerified: true,
  photoURL: 'https://example.com/operator.png',
  providerIds: ['google.com'],
}

class FakeAuthAdapter implements AuthAdapter {
  readonly signInWithGoogle = vi.fn(async () => undefined)
  readonly signOut = vi.fn(async () => undefined)
  readonly getCurrentUserIdToken = vi.fn(async () => 'fresh-id-token')
  readonly unsubscribe = vi.fn()
  private onUser: ((user: AuthUserProfile | null) => void) | null = null
  private onError: ((error: unknown) => void) | null = null

  subscribe(onUser: (user: AuthUserProfile | null) => void, onError: (error: unknown) => void) {
    this.onUser = onUser
    this.onError = onError
    return this.unsubscribe
  }

  emitUser(user: AuthUserProfile | null) {
    this.onUser?.(user)
  }

  emitError(error: unknown) {
    this.onError?.(error)
  }
}

function AuthProbe() {
  const auth = useAuth()
  const [token, setToken] = useState('none')

  return (
    <section>
      <p data-testid="status">{auth.status}</p>
      <p data-testid="identity">
        {auth.user ? `${auth.user.displayName}:${auth.user.emailVerified}` : 'none'}
      </p>
      <p data-testid="operation">{auth.operation ?? 'idle'}</p>
      <p data-testid="error">{auth.error?.message ?? 'none'}</p>
      <p data-testid="token">{token}</p>
      <button type="button" onClick={() => void auth.signInWithGoogle()}>Sign in</button>
      <button type="button" onClick={() => void auth.signOut()}>Sign out</button>
      <button type="button" onClick={() => void auth.getIdToken(true).then(setToken)}>Get token</button>
    </section>
  )
}

describe('AuthProvider', () => {
  it('transitions from initializing through anonymous to authenticated', async () => {
    const adapter = new FakeAuthAdapter()
    render(<AuthProvider adapter={adapter}><AuthProbe /></AuthProvider>)

    expect(screen.getByTestId('status')).toHaveTextContent('initializing')

    act(() => adapter.emitUser(null))
    expect(screen.getByTestId('status')).toHaveTextContent('anonymous')

    act(() => adapter.emitUser(VERIFIED_USER))
    expect(screen.getByTestId('status')).toHaveTextContent('authenticated')
    expect(screen.getByTestId('identity')).toHaveTextContent('Demo Operator:true')
  })

  it('runs Google sign-in, sign-out, and on-demand token retrieval through the adapter', async () => {
    const user = userEvent.setup()
    const adapter = new FakeAuthAdapter()
    render(<AuthProvider adapter={adapter}><AuthProbe /></AuthProvider>)
    act(() => adapter.emitUser(VERIFIED_USER))

    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(adapter.signInWithGoogle).toHaveBeenCalledOnce()

    await user.click(screen.getByRole('button', { name: 'Get token' }))
    expect(await screen.findByText('fresh-id-token')).toBeInTheDocument()
    expect(adapter.getCurrentUserIdToken).toHaveBeenCalledWith(true)

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(adapter.signOut).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.getByTestId('operation')).toHaveTextContent('idle'))
  })

  it('surfaces subscription errors without inventing a user', () => {
    const adapter = new FakeAuthAdapter()
    render(<AuthProvider adapter={adapter}><AuthProbe /></AuthProvider>)

    act(() => adapter.emitError(new Error('observer failed')))

    expect(screen.getByTestId('status')).toHaveTextContent('error')
    expect(screen.getByTestId('identity')).toHaveTextContent('none')
    expect(screen.getByTestId('error')).toHaveTextContent('observer failed')
  })

  it('unsubscribes cleanly when the provider unmounts', () => {
    const adapter = new FakeAuthAdapter()
    const view = render(<AuthProvider adapter={adapter}><AuthProbe /></AuthProvider>)

    view.unmount()

    expect(adapter.unsubscribe).toHaveBeenCalledOnce()
  })

  it('keeps public content usable when Firebase is unconfigured', async () => {
    function UnconfiguredProbe() {
      const auth = useAuth()
      return (
        <main>
          <h1>Public demo</h1>
          <p>{auth.status}</p>
          <button
            type="button"
            onClick={() => void auth.signInWithGoogle().catch((error: Error) => {
              document.body.dataset.authError = error.message
            })}
          >
            Protected action
          </button>
        </main>
      )
    }

    const user = userEvent.setup()
    render(<AuthProvider><UnconfiguredProbe /></AuthProvider>)

    expect(screen.getByRole('heading', { name: 'Public demo' })).toBeVisible()
    expect(screen.getByText('unconfigured')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Protected action' }))
    await waitFor(() => expect(document.body.dataset.authError).toBe('Authentication is not available.'))
    delete document.body.dataset.authError
  })
})
