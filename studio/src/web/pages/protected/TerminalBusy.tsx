/** Shown in a mirror while its stage is in flight.
 *
 * Without this the mirror clears on submit and falls back to "waiting for the
 * first frame", which reads as idle at exactly the moment work is happening.
 */
import { PixelSpinner } from './PixelSpinner'

export function TerminalBusy({ label }: { readonly label: string }) {
  return (
    <div className="tbusy" role="status" aria-live="polite">
      <span className="tbusy__line">
        <span className="tbusy__sigil">$</span>
        <span className="tbusy__label">{label}</span>
        <span className="tbusy__spin"><PixelSpinner /></span>
        <span className="tbusy__caret" aria-hidden="true" />
      </span>
      <span className="tbusy__note">frames appear here as the control plane admits them</span>
    </div>
  )
}
