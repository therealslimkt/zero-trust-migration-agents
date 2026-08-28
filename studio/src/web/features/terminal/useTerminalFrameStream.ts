import { useEffect, useState } from 'react'

import type { LiveWebClient } from '../../client'
import type { SourceId, TerminalFrame } from '../../contracts.generated'
import type { ConnectionState } from '../../pages/protected/state'
import { appendTerminalFrame, parseTerminalFrameSSEBlock } from './stream'

export type TerminalFeedMode = 'live' | 'replay'
export type TerminalFeedConnection = 'connecting' | ConnectionState

export interface TerminalFeed {
  readonly mode: TerminalFeedMode
  readonly frames: readonly TerminalFrame[]
  readonly connection: TerminalFeedConnection
  readonly cursor?: string
}

const INITIAL_FEED: TerminalFeed = { mode: 'live', frames: [], connection: 'connecting' }

interface KeyedTerminalFeed extends TerminalFeed {
  readonly streamKey: string
}

function onlineConnection(): ConnectionState {
  return typeof navigator !== 'undefined' && !navigator.onLine ? 'offline' : 'reconnecting'
}

function reconnectDelay(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, 1_500)
    signal.addEventListener('abort', () => {
      window.clearTimeout(timeout)
      resolve()
    }, { once: true })
  })
}

/** Consumes the bounded authenticated terminal SSE resource and resumes only after the last validated frame. */
export function useTerminalFrameStream(client: LiveWebClient, runId?: string, sourceId?: SourceId): TerminalFeed {
  const streamKey = `${runId ?? ''}\u0000${sourceId ?? ''}`
  const [feed, setFeed] = useState<KeyedTerminalFeed>({ ...INITIAL_FEED, streamKey })

  useEffect(() => {
    if (!runId || !sourceId) return

    const abort = new AbortController()
    let active = true
    let cursor: string | undefined

    const connect = async () => {
      while (active) {
        try {
          const response = await client.openTerminalFrames(runId, sourceId, cursor, abort.signal)
          if (!response.body) throw new Error('Terminal stream response body is unavailable.')
          setFeed((current) => current.streamKey === streamKey
            ? { ...current, connection: 'live' }
            : { ...INITIAL_FEED, streamKey, connection: 'live' })

          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          while (active) {
            const chunk = await reader.read()
            if (chunk.done) {
              buffer = (buffer + decoder.decode()).replaceAll('\r\n', '\n')
              break
            }
            buffer = (buffer + decoder.decode(chunk.value, { stream: true })).replaceAll('\r\n', '\n')
            let boundary = buffer.indexOf('\n\n')
            while (boundary >= 0) {
              const frame = parseTerminalFrameSSEBlock(buffer.slice(0, boundary), { runId, sourceId })
              buffer = buffer.slice(boundary + 2)
              if (frame) {
                cursor = frame.frameId
                setFeed((current) => ({
                  mode: 'live',
                  connection: 'live',
                  cursor,
                  frames: appendTerminalFrame(current.streamKey === streamKey ? current.frames : [], frame),
                  streamKey,
                }))
              }
              boundary = buffer.indexOf('\n\n')
            }
          }
          if (active) setFeed((current) => current.streamKey === streamKey
            ? { ...current, connection: 'reconnecting' }
            : { ...INITIAL_FEED, streamKey, connection: 'reconnecting' })
        } catch {
          if (!active || abort.signal.aborted) return
          setFeed((current) => current.streamKey === streamKey
            ? { ...current, connection: onlineConnection() }
            : { ...INITIAL_FEED, streamKey, connection: onlineConnection() })
        }
        await reconnectDelay(abort.signal)
      }
    }

    void connect()
    return () => {
      active = false
      abort.abort()
    }
  }, [client, runId, sourceId, streamKey])

  return feed.streamKey === streamKey ? feed : INITIAL_FEED
}
