import manifest from './keraunDemoManifest.json'
import { RecordedReplayPage } from './RecordedReplayPage'
import type { DemoManifest } from '../../contracts.generated'

export function KeraunDemoRoute() {
  return <RecordedReplayPage manifest={manifest as unknown as DemoManifest} />
}
