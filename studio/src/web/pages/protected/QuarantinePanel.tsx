import { useState } from 'react'

import { PixelIcon } from '../../shared/ui'
import { stages, StageError, type QuarantineRow } from './stageClient'

/** The records the pipeline refused, and why.
 *
 * A rejected row is not a failure to hide: it is the point of the exercise.
 * These rows carry enough to locate the record in the source and enough to
 * explain the refusal, and never the record's contents.
 */
export function QuarantinePanel({
  cartridge,
  rows,
  read,
}: {
  readonly cartridge: string
  readonly rows: readonly QuarantineRow[]
  readonly read: number
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (rows.length === 0) return null

  const download = async () => {
    setBusy(true)
    setError(null)
    try {
      const manifest = await stages.quarantine(cartridge)
      const blob = new Blob([manifest.csv], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = manifest.filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setError(caught instanceof StageError ? caught.message : 'Could not build the manifest.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="quar">
      <header className="quar__head">
        <PixelIcon name="alert-triangle" size="xs" color="google-red" />
        <div>
          <h3>{rows.length} of {read} records quarantined</h3>
          <p>
            Structurally invalid on the source side. They are isolated, not repaired or
            guessed, and never reach the warehouse.
          </p>
        </div>
        <button type="button" className="quar__toggle" aria-expanded={open}
                onClick={() => setOpen((value) => !value)}>
          {open ? 'Hide' : 'Inspect'}
        </button>
      </header>

      {open ? (
        <>
          <div className="quar__table" role="region" aria-label="Quarantined records">
            <table>
              <thead>
                <tr>
                  <th>Source key</th><th>Reason</th><th>COMP-3 field</th><th>Why it failed</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.aban8}>
                    <td>{row.sourceTable}.{row.sourceKey}</td>
                    <td>{row.reason}</td>
                    <td className="quar__hex">{row.comp3FieldHex}</td>
                    <td>{row.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="quar__actions">
            <button type="button" onClick={() => void download()} disabled={busy}>
              <PixelIcon name="database" size="xs" />
              {busy ? 'Building…' : 'Download manifest (CSV)'}
            </button>
            <span className="quar__note">
              Locating keys and failure reasons only — no source values leave the perimeter.
            </span>
          </div>
          {error ? <p className="quar__error">{error}</p> : null}
        </>
      ) : null}
    </section>
  )
}
