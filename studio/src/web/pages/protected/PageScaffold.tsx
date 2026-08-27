import type { ReactNode } from 'react'

import type { ConnectionState } from './state'
import './protected.css'

interface PageScaffoldProps {
  readonly eyebrow: string
  readonly title: string
  readonly description: string
  readonly actions?: ReactNode
  readonly connection?: ConnectionState
  readonly stale?: boolean
  readonly lastUpdatedAt?: string
  readonly children: ReactNode
}

export function PageScaffold({
  eyebrow,
  title,
  description,
  actions,
  connection,
  stale = false,
  lastUpdatedAt,
  children,
}: PageScaffoldProps) {
  const showFreshness = stale || connection === 'reconnecting' || connection === 'offline'

  return (
    <main id="main-content" className="protected-page">
      <header className="protected-page__header">
        <div>
          <p className="protected-page__eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="protected-page__lede">{description}</p>
        </div>
        {actions ? <div className="protected-page__actions">{actions}</div> : null}
      </header>

      {showFreshness ? (
        <div
          className={`protected-notice protected-notice--${connection === 'offline' ? 'error' : 'warning'}`}
          role="status"
        >
          <strong>
            {connection === 'reconnecting'
              ? 'Reconnecting to the event stream'
              : connection === 'offline'
                ? 'Live updates are offline'
                : 'This snapshot may be stale'}
          </strong>
          <span>
            {lastUpdatedAt
              ? <>Last authenticated update <time dateTime={lastUpdatedAt}>{lastUpdatedAt}</time>.</>
              : 'No more recent authenticated snapshot is available.'}
          </span>
        </div>
      ) : null}

      {children}
    </main>
  )
}

interface StatePanelProps {
  readonly kind: 'loading' | 'empty' | 'error'
  readonly title: string
  readonly message: string
  readonly onRetry?: () => void
}

export function StatePanel({ kind, title, message, onRetry }: StatePanelProps) {
  return (
    <section
      className={`protected-state protected-state--${kind}`}
      aria-live={kind === 'error' ? 'assertive' : 'polite'}
      aria-busy={kind === 'loading'}
    >
      <span className="protected-state__glyph" aria-hidden="true">
        {kind === 'loading' ? '···' : kind === 'error' ? '!' : '◇'}
      </span>
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <button className="protected-button protected-button--secondary" type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </section>
  )
}

export function Metric({ label, value }: { readonly label: string; readonly value: ReactNode }) {
  return (
    <div className="protected-metric">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function CodeValue({ children }: { readonly children: ReactNode }) {
  return <code className="protected-code">{children}</code>
}
