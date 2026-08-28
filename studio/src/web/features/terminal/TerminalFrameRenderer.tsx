import type { TerminalFrame, TerminalLane } from '../../contracts.generated'

import type { TerminalFeed } from './useTerminalFrameStream'
import './terminal.css'

export interface TerminalFrameRendererProps {
  readonly feed: TerminalFeed
  readonly lane: TerminalLane
  readonly label: string
}

function emptyMessage(feed: TerminalFeed): string {
  if (feed.mode === 'replay') return 'RECORDED REPLAY · NO EXACT TERMINAL FRAMES WERE CAPTURED'
  if (feed.connection === 'connecting') return 'CONNECTING · WAITING FOR PRODUCER-ADMITTED FRAMES'
  if (feed.connection === 'offline') return 'OFFLINE · NO CACHED TERMINAL FRAMES AVAILABLE'
  if (feed.connection === 'reconnecting') return 'RECONNECTING · NO TERMINAL FRAMES RECEIVED YET'
  return 'STREAM OPEN · WAITING FOR THE FIRST EXACT TERMINAL FRAME'
}

export function TerminalFrameRenderer({ feed, lane, label }: TerminalFrameRendererProps) {
  const frames = feed.frames.filter((frame) => frame.lane === lane)
  if (frames.length === 0) {
    return <div className="live-terminal-empty" role="status"><span>{emptyMessage(feed)}</span><small>No output is synthesized while the stream is empty.</small></div>
  }

  return (
    <ol className="live-terminal-frames" role="log" aria-label={`${label} exact terminal frames`} aria-live="off">
      {frames.map((frame, index) => (
        <li
          key={frame.frameId}
          className={`live-terminal-frame live-terminal-frame--${frame.stream} live-terminal-frame--${frame.severity}`}
          data-frame-id={frame.frameId}
          data-lane-sequence={frame.laneSequence}
          data-active={index === frames.length - 1}
        >
          <span className="live-terminal-frame__comment">[{frame.timestamp}] #{frame.laneSequence}</span>
          <span className="live-terminal-frame__identity">{frame.producer}</span>
          <span className="live-terminal-frame__keyword">{frame.stream}</span>
          <span className="live-terminal-frame__tool">{frame.tool}</span>
          <code className="live-terminal-frame__line">{frame.line}</code>
        </li>
      ))}
    </ol>
  )
}

export function TerminalActorLabels({ frames, lane }: { readonly frames: readonly TerminalFrame[]; readonly lane: TerminalLane }) {
  const labels = Array.from(new Map(
    frames
      .filter((frame) => frame.lane === lane)
      .map((frame) => [`${frame.producer}\u0000${frame.tool}`, { producer: frame.producer, tool: frame.tool }]),
  ).values())

  if (labels.length === 0) return <span className="live-terminal-actors__empty">No producer or tool labels received</span>
  return <div className="live-terminal-actors" aria-label="Producer and tool labels">{labels.map((label) => <span key={`${label.producer}:${label.tool}`}><strong>{label.producer}</strong><small>{label.tool}</small></span>)}</div>
}
