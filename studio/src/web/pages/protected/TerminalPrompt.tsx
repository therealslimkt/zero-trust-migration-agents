import { useRef, useState } from 'react'

import { StageError, type StageRows } from './stageClient'

/** An input line inside a mirror.

    Results are not rendered here. The executor mirrors every returned row back
    through the control plane as terminal frames, so the output arrives in the
    frame stream above exactly like a real shell. Drawing a second copy in the
    prompt was what pushed the input out of the window. */
export function TerminalPrompt({
  placeholder,
  onSubmit,
  disabled,
  hint,
}: {
  readonly placeholder: string
  readonly onSubmit: (sql: string) => Promise<StageRows>
  readonly disabled?: boolean
  readonly hint?: string
}) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  const submit = async () => {
    const sql = value.trim()
    if (!sql || busy) return
    setBusy(true)
    setError(null)
    try {
      await onSubmit(sql)
      setValue('')
    } catch (caught) {
      setError(caught instanceof StageError ? caught.message : 'The query failed.')
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  return (
    <div className="tprompt">
      {error ? <pre className="tprompt__err">{error}</pre> : null}
      <div className="tprompt__line">
        <span className="tprompt__sigil">$</span>
        <textarea
          ref={input}
          rows={1}
          spellCheck={false}
          value={value}
          disabled={disabled || busy}
          placeholder={disabled ? (hint ?? 'not ready') : placeholder}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void submit()
            }
          }}
        />
        <button type="button" onClick={() => void submit()} disabled={disabled || busy || !value.trim()}>
          {busy ? '…' : 'Run'}
        </button>
      </div>
      <span className="tprompt__help">
        Paste a read-only SELECT and press Enter. Output appears above.
      </span>
    </div>
  )
}
