import { describe, expect, it, vi } from 'vitest'

import { createLocalDemoAuthAdapter, LOCAL_DEMO_ID_TOKEN } from './localDemoAdapter'

describe('local demo auth adapter', () => {
  it('signs in explicitly, emits the loopback identity, and signs out', async () => {
    window.sessionStorage.clear()
    const adapter = createLocalDemoAuthAdapter()
    const onUser = vi.fn()
    adapter.subscribe(onUser, vi.fn())

    expect(onUser).toHaveBeenLastCalledWith(null)
    await adapter.signInWithGoogle()
    expect(onUser).toHaveBeenLastCalledWith(expect.objectContaining({ uid: 'local-demo-operator' }))
    await expect(adapter.getCurrentUserIdToken()).resolves.toBe(LOCAL_DEMO_ID_TOKEN)

    await adapter.signOut()
    expect(onUser).toHaveBeenLastCalledWith(null)
    await expect(adapter.getCurrentUserIdToken()).rejects.toThrow('No authenticated local demo user')
  })
})
