import goControlPlane from '../../assets/architecture/go-control-plane.svg?raw'
import platform from '../../assets/architecture/platform.svg?raw'

import { DiagramFrame } from './DiagramFrame'

/** The architecture drawings, inline.
 *
 * Rendered as live SVG rather than an exported image so they follow the site
 * theme, stay selectable, and scale without going soft. Every colour is a CSS
 * custom property, so light and dark are the same drawing.
 */
export function ArchitectureDiagram() {
  return (
    <div className="arch">
      <DiagramFrame
        title="KERAUN PLATFORM"
        breadcrumb="architecture/platform"
        markup={platform}
        caption="Sealed sources, the control plane, the fleet and its limits, one human decision, then trusted execution into BigQuery."
      />
      <DiagramFrame
        title="GO CONTROL PLANE"
        breadcrumb="architecture/studio-backend"
        markup={goControlPlane}
        caption="Three separately credentialed doors, frame admission, the frozen state machine, and the durable state the browser reads but never owns."
      />
    </div>
  )
}
