import { useEffect, useState } from 'react'

import { PixelIcon } from '../../shared/ui'

const ZOOMS = [0.75, 1, 1.35, 1.75, 2.25, 3] as const
const DEFAULT_ZOOM = 1

/** A diagram in the same window chassis as the terminals.
 *
 * Green expands it to the viewport, yellow collapses it to its title bar, and
 * the magnifiers step through fixed zoom levels. Expanded, the canvas scrolls
 * in both directions so a zoomed drawing stays reachable.
 */
export function DiagramFrame({
  title,
  breadcrumb,
  caption,
  markup,
}: {
  readonly title: string
  readonly breadcrumb: string
  readonly caption: string
  readonly markup: string
}) {
  const [maximized, setMaximized] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [zoom, setZoom] = useState(DEFAULT_ZOOM)

  useEffect(() => {
    if (!maximized) return
    const leave = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMaximized(false)
    }
    window.addEventListener('keydown', leave)
    return () => window.removeEventListener('keydown', leave)
  }, [maximized])

  const step = (direction: 1 | -1) => {
    const next = ZOOMS.indexOf(zoom as (typeof ZOOMS)[number]) + direction
    if (next >= 0 && next < ZOOMS.length) setZoom(ZOOMS[next])
  }

  return (
    <figure className={`dframe${maximized ? ' dframe--max' : ''}${collapsed ? ' dframe--min' : ''}`}>
      <header className="dframe__bar">
        <span className="dframe__dots">
          <button type="button" className="dframe__dot dframe__dot--red" disabled
                  aria-label="Close unavailable" title="Close unavailable" />
          <button type="button" className="dframe__dot dframe__dot--yellow"
                  disabled={maximized}
                  aria-label={collapsed ? 'Expand diagram' : 'Collapse diagram'}
                  title={maximized ? 'Restore the window first' : collapsed ? 'Expand' : 'Collapse'}
                  onClick={() => setCollapsed((value) => !value)} />
          <button type="button" className="dframe__dot dframe__dot--green"
                  aria-pressed={maximized}
                  aria-label={maximized ? 'Restore diagram' : 'Maximize diagram'}
                  title={maximized ? 'Restore' : 'Maximize'}
                  onClick={() => { setMaximized((value) => !value); setCollapsed(false) }} />
        </span>
        <span className="dframe__title">{title}</span>
        <span className="dframe__crumb">{breadcrumb}</span>
        <span className="dframe__zoom">
          <button type="button" onClick={() => step(-1)} disabled={zoom === ZOOMS[0]}
                  aria-label="Zoom out" title="Zoom out">
            <PixelIcon name="zoom-out" size="xs" />
          </button>
          <span className="dframe__level">{Math.round(zoom * 100)}%</span>
          <button type="button" onClick={() => step(1)} disabled={zoom === ZOOMS[ZOOMS.length - 1]}
                  aria-label="Zoom in" title="Zoom in">
            <PixelIcon name="zoom-in" size="xs" />
          </button>
          <button type="button" className="dframe__reset" onClick={() => setZoom(DEFAULT_ZOOM)}
                  disabled={zoom === DEFAULT_ZOOM} title="Reset zoom">reset</button>
        </span>
      </header>

      {collapsed ? null : (
        <div className="dframe__scroll">
          <div
            className="dframe__canvas"
            style={{ width: `${zoom * 100}%` }}
            dangerouslySetInnerHTML={{ __html: markup }}
          />
        </div>
      )}

      {collapsed || maximized ? null : <figcaption>{caption}</figcaption>}
    </figure>
  )
}
