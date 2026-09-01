import { useEffect, useRef, useState } from 'react'

import type { TerminalFeed } from '../../features/terminal'

/** Show only the frames this session produced, one at a time.
 *
 * A run accumulates frames from every stage anyone has ever driven against it.
 * Rather than guess which of those are "new" from counts or timing, the page
 * marks the frame count at the moment *you* start a stage: everything before
 * that mark is prior history and stays hidden, everything after is your work.
 * Deterministic, and it needs no change to the frame contract.
 *
 * Pacing applies only to the display of frames the control plane has already
 * admitted. Nothing is invented, reordered, or withheld.
 */
export function usePacedFeed(feed: TerminalFeed, mark: number | null, msPerFrame = 90) {
  const [revealed, setRevealed] = useState(0)
  const [skipped, setSkipped] = useState(false)
  const lastMark = useRef(mark)
  const total = feed.frames.length

  // A fresh mark means a new stage: restart the playback.
  if (lastMark.current !== mark) {
    lastMark.current = mark
    if (revealed !== 0) setRevealed(0)
    if (skipped) setSkipped(false)
  }

  const base = mark ?? total          // nothing marked yet: show nothing
  const pending = Math.max(0, total - base)
  const shown = skipped ? pending : Math.min(revealed, pending)

  useEffect(() => {
    if (skipped || shown >= pending) return
    const timer = window.setTimeout(() => setRevealed((n) => n + 1), msPerFrame)
    return () => window.clearTimeout(timer)
  }, [shown, pending, skipped, msPerFrame])

  const visible = feed.frames.slice(base, base + shown)
  return {
    feed: { ...feed, frames: visible, cursor: visible.at(-1)?.frameId },
    playing: shown < pending,
    shown,
    total: pending,
    skip: () => setSkipped(true),
  }
}
