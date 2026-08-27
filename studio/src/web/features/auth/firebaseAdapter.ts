import { getApps, initializeApp } from 'firebase/app'
import {
  GoogleAuthProvider,
  getAuth,
  inMemoryPersistence,
  initializeAuth,
  onAuthStateChanged,
  signInWithPopup,
  signOut,
} from 'firebase/auth'
import type { Auth, User } from 'firebase/auth'

import type { FirebasePublicConfig } from './config'
import type { AuthAdapter, AuthUserProfile } from './types'

const FIREBASE_APP_NAME = 'zero-trust-migration-web'

function getOrInitializeAuth(config: FirebasePublicConfig): Auth {
  const existingApp = getApps().find((app) => app.name === FIREBASE_APP_NAME)
  const app = existingApp ?? initializeApp(config, FIREBASE_APP_NAME)

  try {
    // In-memory persistence ensures this application never writes ID tokens or
    // refresh credentials to browser storage. A refresh requires sign-in again.
    return initializeAuth(app, { persistence: inMemoryPersistence })
  } catch (error) {
    if (
      error &&
      typeof error === 'object' &&
      'code' in error &&
      error.code === 'auth/already-initialized'
    ) {
      return getAuth(app)
    }
    throw error
  }
}

function profileFromFirebaseUser(user: User): AuthUserProfile {
  const googleProfile = user.providerData.find((provider) => provider.providerId === 'google.com')
  const verifiedEmail = googleProfile?.email ?? null

  return Object.freeze({
    uid: user.uid,
    // Display metadata comes from the authenticated Google provider record,
    // rather than caller-controlled route state or editable application data.
    displayName: googleProfile?.displayName ?? null,
    email: verifiedEmail,
    emailVerified: Boolean(
      verifiedEmail && user.emailVerified && verifiedEmail === user.email,
    ),
    photoURL: googleProfile?.photoURL ?? null,
    providerIds: Object.freeze(
      Array.from(new Set(user.providerData.map((provider) => provider.providerId))).sort(),
    ),
  })
}

export function createFirebaseAuthAdapter(config: FirebasePublicConfig): AuthAdapter {
  const auth = getOrInitializeAuth(config)
  const googleProvider = new GoogleAuthProvider()
  googleProvider.setCustomParameters({ prompt: 'select_account' })

  return {
    subscribe(onUser, onError) {
      return onAuthStateChanged(
        auth,
        (user) => onUser(user ? profileFromFirebaseUser(user) : null),
        onError,
      )
    },
    async signInWithGoogle() {
      await signInWithPopup(auth, googleProvider)
    },
    async signOut() {
      await signOut(auth)
    },
    async getCurrentUserIdToken(forceRefresh = false) {
      const user = auth.currentUser
      if (!user) throw new Error('No authenticated Firebase user is available.')
      // Return the token directly to the caller. It is never retained by this
      // adapter, React state, localStorage, or sessionStorage.
      return user.getIdToken(forceRefresh)
    },
  }
}
