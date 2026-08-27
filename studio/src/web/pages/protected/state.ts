export type ConnectionState = 'live' | 'reconnecting' | 'offline'

interface ResourceMeta {
  readonly connection?: ConnectionState
  readonly stale?: boolean
  readonly lastUpdatedAt?: string
}

export type ResourceState<T> =
  | (ResourceMeta & { readonly status: 'loading' })
  | (ResourceMeta & { readonly status: 'empty'; readonly message?: string })
  | (ResourceMeta & { readonly status: 'error'; readonly message: string })
  | (ResourceMeta & { readonly status: 'ready'; readonly data: T })

export function isReady<T>(state: ResourceState<T>): state is ResourceMeta & {
  readonly status: 'ready'
  readonly data: T
} {
  return state.status === 'ready'
}
