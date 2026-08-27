import type { AuthAdapter, AuthUserProfile } from './types'

/**
 * Public, non-secret credential accepted only by the loopback-only Go demo
 * profile. Production builds cannot select this adapter.
 */
export const LOCAL_DEMO_ID_TOKEN = 'ztm-loopback-demo-v1'

const SESSION_KEY = 'ztm-local-demo-signed-in'
const LOCAL_USER: AuthUserProfile = {
  uid: 'local-demo-operator',
  displayName: 'Local Demo Operator',
  email: 'operator@local.demo',
  emailVerified: true,
  photoURL: null,
  providerIds: ['local-demo'],
}

export function createLocalDemoAuthAdapter(): AuthAdapter {
  let currentUser = window.sessionStorage.getItem(SESSION_KEY) === 'true' ? LOCAL_USER : null
  let notify: ((user: AuthUserProfile | null) => void) | null = null

  return {
    subscribe(onUser) {
      notify = onUser
      onUser(currentUser)
      return () => { notify = null }
    },
    async signInWithGoogle() {
      currentUser = LOCAL_USER
      window.sessionStorage.setItem(SESSION_KEY, 'true')
      notify?.(currentUser)
    },
    async signOut() {
      currentUser = null
      window.sessionStorage.removeItem(SESSION_KEY)
      notify?.(null)
    },
    async getCurrentUserIdToken() {
      if (!currentUser) throw new Error('No authenticated local demo user is available.')
      return LOCAL_DEMO_ID_TOKEN
    },
  }
}
