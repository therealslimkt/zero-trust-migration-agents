import { describe, expect, it } from 'vitest'

import { readFirebasePublicConfig } from './config'

describe('readFirebasePublicConfig', () => {
  it('reads only the required public Firebase configuration', () => {
    const result = readFirebasePublicConfig({
      VITE_FIREBASE_API_KEY: ' public-api-key ',
      VITE_FIREBASE_AUTH_DOMAIN: 'demo.firebaseapp.com',
      VITE_FIREBASE_PROJECT_ID: 'demo-project',
      VITE_FIREBASE_APP_ID: '1:123:web:abc',
      VITE_FIREBASE_PRIVATE_KEY: 'must-not-be-read',
    })

    expect(result).toEqual({
      config: {
        apiKey: 'public-api-key',
        authDomain: 'demo.firebaseapp.com',
        projectId: 'demo-project',
        appId: '1:123:web:abc',
      },
      missing: [],
    })
    expect(result.config).not.toHaveProperty('privateKey')
  })

  it('fails closed when a required setting is missing or contains control characters', () => {
    const result = readFirebasePublicConfig({
      VITE_FIREBASE_API_KEY: 'public-api-key',
      VITE_FIREBASE_AUTH_DOMAIN: 'demo.firebaseapp.com\nmalformed',
      VITE_FIREBASE_PROJECT_ID: 'demo-project',
    })

    expect(result.config).toBeNull()
    expect(result.missing).toEqual([
      'VITE_FIREBASE_AUTH_DOMAIN',
      'VITE_FIREBASE_APP_ID',
    ])
  })
})
