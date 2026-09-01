import { useState } from 'react'

import { PixelIcon, type PixelIconName } from '../../shared/ui'
import { StageError, type StageQuery } from './stageClient'

type Props = {
  readonly step: string
  readonly lane?: string
  readonly maximizedLane?: string | null
  readonly title: string
  readonly subtitle: string
  readonly stackLabel: string
  readonly stackNote: string
  readonly chips: readonly { readonly icon: PixelIconName; readonly label: string;
                             readonly tone?: 'blue' | 'green' | 'gold' | 'go' }[]
  readonly icon: PixelIconName
  readonly accent: 'blue' | 'yellow' | 'green'
  readonly runLabel: string
  readonly onRun: () => Promise<void>
  readonly ready: boolean
  readonly blockedReason?: string
  /** Already run: the control stays visible but refuses a second press. */
  readonly done?: boolean
  readonly doneLabel?: string
  readonly queries?: readonly StageQuery[]
  readonly children: React.ReactNode
}

export function StageColumn(props: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [allOpen, setAllOpen] = useState(false)

  const copy = async (text: string, key: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
      } else {
        // Fallback for contexts where the async clipboard is unavailable.
        const scratch = document.createElement('textarea')
        scratch.value = text
        scratch.setAttribute('readonly', '')
        scratch.style.position = 'fixed'
        scratch.style.opacity = '0'
        document.body.appendChild(scratch)
        scratch.select()
        document.execCommand('copy')
        document.body.removeChild(scratch)
      }
      setCopied(key)
      window.setTimeout(() => setCopied((current) => (current === key ? null : current)), 1600)
    } catch {
      setError('Could not reach the clipboard; select the query and copy manually.')
    }
  }

  const run = async () => {
    setBusy(true); setError(null)
    try { await props.onRun() } catch (caught) {
      setError(caught instanceof StageError ? caught.message : 'The stage failed.')
    } finally { setBusy(false) }
  }


  return (
    <section className={[
      'stage', `stage--${props.accent}`,
      props.maximizedLane && props.maximizedLane === props.lane ? 'stage--focus' : '',
      props.maximizedLane && props.maximizedLane !== props.lane ? 'stage--dimmed' : '',
    ].filter(Boolean).join(' ')}>
      <header className="stage__head">
        <span className="stage__step">{props.step}</span>
        <PixelIcon name={props.icon} size="sm" color="muted" />
        <div>
          <h2>{props.title}</h2>
          <p>{props.subtitle}</p>
        </div>
      </header>

      <div className="stage__stack">
        <span className="stage__stack-label">{props.stackLabel}</span>
        <div className="stage__chips">
          {props.chips.map((chip) => (
            <span key={chip.label} className={`stage__chip stage__chip--${chip.tone ?? 'blue'}`}>
              <PixelIcon name={chip.icon} size="xs" />
              <span className="stage__chip-label">{chip.label}</span>
            </span>
          ))}
        </div>
        <p className="stage__stack-note">{props.stackNote}</p>
      </div>

      <button
        type="button"
        className={props.done ? 'stage__run stage__run--done' : 'stage__run'}
        onClick={() => void run()}
        disabled={busy || !props.ready || Boolean(props.done)}
        aria-disabled={props.done || undefined}
        title={
          props.done
            ? props.doneLabel ?? 'Already run; pick another cartridge to start over'
            : props.ready
              ? undefined
              : props.blockedReason
        }
      >
        {busy ? 'Running…' : props.done ? `✓  ${props.doneLabel ?? 'Done'}` : `▶  ${props.runLabel}`}
      </button>

      <div className="stage__rest">
      {!props.ready && props.blockedReason ? (
        <p className="stage__blocked">{props.blockedReason}</p>
      ) : null}
      {props.queries?.length ? (
        <div className="stage__queries">
          <div className="stage__queries-head">
            <span className="stage__queries-label">Run one yourself</span>
            <button type="button" className="stage__toggle-all"
                    aria-expanded={allOpen}
                    onClick={() => setAllOpen((open) => !open)}>
              {allOpen ? 'Collapse all' : 'Expand all'}
            </button>
          </div>
          {props.queries.map((entry) => (
            <details key={entry.title} className="stage__query" open={allOpen}>
              <summary>{entry.title}</summary>
              <pre>{entry.sql}</pre>
              <button
                type="button"
                className={copied === entry.title ? 'stage__copy stage__copy--done' : 'stage__copy'}
                aria-label={`Copy the ${entry.title} query`}
                title={copied === entry.title ? 'Copied' : 'Copy query'}
                onClick={() => void copy(entry.sql, entry.title)}
              >
                <PixelIcon name={copied === entry.title ? 'check-pixel' : 'copy'} size="xs" />
              </button>
            </details>
          ))}
        </div>
      ) : null}

      {error ? <p className="stage__error">{error}</p> : null}


      {props.children}
      </div>
    </section>
  )
}
