import type { FormEvent } from 'react'
import type {
  CloudConnectionResponse,
  CloudSetupRequest,
  CloudSetupResponse,
  CloudVerifyResponse,
} from '../../contracts.generated'

import { CodeValue, Metric, PageScaffold, StatePanel } from './PageScaffold'
import type { ResourceState } from './state'

function MissingCapabilities({ capabilities }: { readonly capabilities?: readonly string[] }) {
  if (!capabilities || capabilities.length === 0) return null
  return (
    <div className="cloud-capabilities" role="status">
      <strong>Missing capabilities</strong>
      <ul>{capabilities.map((capability) => <li key={capability}><CodeValue>{capability}</CodeValue></li>)}</ul>
    </div>
  )
}

function ConnectionPanel({ state }: { readonly state: ResourceState<CloudConnectionResponse> }) {
  if (state.status === 'loading') {
    return <StatePanel kind="loading" title="Checking connection" message="Waiting for the authenticated setup record." />
  }
  if (state.status === 'error') {
    return <StatePanel kind="error" title="Connection check failed" message={state.message} />
  }
  if (state.status === 'empty') {
    return <StatePanel kind="empty" title="No cloud setup" message={state.message ?? 'Generate a scoped setup command to begin.'} />
  }

  const connection = state.data
  return (
    <section className={`cloud-connection cloud-connection--${connection.status}`} aria-labelledby="cloud-connection-heading">
      <header>
        <div>
          <p className="protected-kicker">Current connection</p>
          <h2 id="cloud-connection-heading">{connection.status.replace('_', ' ')}</h2>
        </div>
        <span className={`protected-pill protected-pill--${connection.status === 'verified' ? 'success' : connection.status === 'degraded' ? 'danger' : 'warning'}`}>
          {connection.status}
        </span>
      </header>
      <dl className="protected-definition-grid">
        {connection.setupId ? <div><dt>Setup ID</dt><dd><CodeValue>{connection.setupId}</CodeValue></dd></div> : null}
        {connection.projectId ? <div><dt>Project</dt><dd><CodeValue>{connection.projectId}</CodeValue></dd></div> : null}
        {connection.region ? <div><dt>Region</dt><dd><CodeValue>{connection.region}</CodeValue></dd></div> : null}
        {connection.datasetPrefix ? <div><dt>Dataset prefix</dt><dd><CodeValue>{connection.datasetPrefix}</CodeValue></dd></div> : null}
        {connection.verifiedAt ? <div><dt>Verified</dt><dd><time dateTime={connection.verifiedAt}>{connection.verifiedAt}</time></dd></div> : null}
      </dl>
      <MissingCapabilities capabilities={connection.missingCapabilities} />
    </section>
  )
}

function SetupCommand({ setup, onCopy }: { readonly setup: CloudSetupResponse; readonly onCopy?: (command: string) => void }) {
  return (
    <section className="cloud-command" aria-labelledby="cloud-command-heading">
      <header>
        <div>
          <p className="protected-kicker">Reviewed setup</p>
          <h2 id="cloud-command-heading">Run in Cloud Shell</h2>
        </div>
        {onCopy ? (
          <button className="protected-button protected-button--secondary" type="button" onClick={() => onCopy(setup.command)}>
            Copy command
          </button>
        ) : null}
      </header>
      <pre tabIndex={0}><code>{setup.command}</code></pre>
      <dl className="cloud-command__facts">
        <Metric label="Setup ID" value={<CodeValue>{setup.setupId}</CodeValue>} />
        <Metric label="Command digest" value={<CodeValue>{setup.commandDigest}</CodeValue>} />
        <Metric label="Expires" value={<time dateTime={setup.expiresAt}>{setup.expiresAt}</time>} />
      </dl>
    </section>
  )
}

export interface CloudSettingsPageProps {
  readonly connection: ResourceState<CloudConnectionResponse>
  readonly setupRequest: CloudSetupRequest
  readonly setup: ResourceState<CloudSetupResponse>
  readonly receipt: string
  readonly verification: ResourceState<CloudVerifyResponse>
  readonly submitting?: boolean
  readonly onSetupRequestChange: (request: CloudSetupRequest) => void
  readonly onReceiptChange: (receipt: string) => void
  readonly onGenerateSetup?: (request: CloudSetupRequest) => void
  readonly onVerify?: (setupId: string, receipt: string) => void
  readonly onCopyCommand?: (command: string) => void
}

export function CloudSettingsPage({
  connection,
  setupRequest,
  setup,
  receipt,
  verification,
  submitting = false,
  onSetupRequestChange,
  onReceiptChange,
  onGenerateSetup,
  onVerify,
  onCopyCommand,
}: CloudSettingsPageProps) {
  const update = <Key extends keyof CloudSetupRequest>(key: Key, value: CloudSetupRequest[Key]) => {
    onSetupRequestChange({ ...setupRequest, [key]: value })
  }

  const generate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    onGenerateSetup?.(setupRequest)
  }

  const verify = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (setup.status === 'ready') onVerify?.(setup.data.setupId, receipt)
  }

  return (
    <PageScaffold
      eyebrow="Bring your own Google Cloud"
      title="Cloud connection"
      description="Generate scoped infrastructure in your own project, then return only the non-secret verification receipt."
      connection={connection.connection}
      stale={connection.stale}
      lastUpdatedAt={connection.lastUpdatedAt}
    >
      <aside className="protected-safety-note protected-safety-note--prominent">
        Never paste service-account JSON, access keys, refresh tokens, ADC files, or any other credential into this page.
      </aside>

      <ConnectionPanel state={connection} />

      <section className="protected-step" aria-labelledby="cloud-settings-heading">
        <div className="protected-step__number">01</div>
        <div className="protected-step__content">
          <h2 id="cloud-settings-heading">Choose non-secret resource settings</h2>
          <form className="protected-form" onSubmit={generate}>
            <label>Google Cloud project ID<input required value={setupRequest.projectId} onChange={(event) => update('projectId', event.target.value)} /></label>
            <label>Region<input required value={setupRequest.region} onChange={(event) => update('region', event.target.value)} /></label>
            <label>Dataset prefix<input required value={setupRequest.datasetPrefix} onChange={(event) => update('datasetPrefix', event.target.value)} /></label>
            <div className="protected-form__actions protected-form__wide">
              <button className="protected-button protected-button--primary" type="submit" disabled={submitting || !onGenerateSetup}>
                {submitting ? 'Generating…' : 'Generate reviewed command'}
              </button>
            </div>
          </form>
        </div>
      </section>

      <section className="protected-step" aria-labelledby="run-command-heading">
        <div className="protected-step__number">02</div>
        <div className="protected-step__content">
          <h2 id="run-command-heading">Run the reviewed command</h2>
          {setup.status === 'loading' ? <StatePanel kind="loading" title="Generating setup" message="Waiting for a server-reviewed command." /> : null}
          {setup.status === 'empty' ? <StatePanel kind="empty" title="No setup command yet" message={setup.message ?? 'Submit the non-secret settings above.'} /> : null}
          {setup.status === 'error' ? <StatePanel kind="error" title="Setup generation failed" message={setup.message} /> : null}
          {setup.status === 'ready' ? <SetupCommand setup={setup.data} onCopy={onCopyCommand} /> : null}
        </div>
      </section>

      <section className="protected-step" aria-labelledby="verify-setup-heading">
        <div className="protected-step__number">03</div>
        <div className="protected-step__content">
          <h2 id="verify-setup-heading">Verify the receipt</h2>
          <form className="protected-form protected-form--receipt" onSubmit={verify}>
            <label>
              Non-secret verification receipt
              <input
                required
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={receipt}
                onChange={(event) => onReceiptChange(event.target.value)}
              />
            </label>
            <button className="protected-button protected-button--primary" type="submit" disabled={setup.status !== 'ready' || !receipt || submitting || !onVerify}>
              Verify setup
            </button>
          </form>
          {verification.status === 'loading' ? <StatePanel kind="loading" title="Verifying receipt" message="Checking required capabilities without requesting a credential." /> : null}
          {verification.status === 'empty' ? <p className="protected-muted">No verification has been submitted.</p> : null}
          {verification.status === 'error' ? <StatePanel kind="error" title="Verification failed" message={verification.message} /> : null}
          {verification.status === 'ready' ? (
            <section className={`cloud-verification cloud-verification--${verification.data.status}`} aria-live="polite">
              <h3>Setup {verification.data.status}</h3>
              <dl className="protected-definition-grid">
                <div><dt>Setup ID</dt><dd><CodeValue>{verification.data.setupId}</CodeValue></dd></div>
                <div><dt>Project</dt><dd><CodeValue>{verification.data.projectId}</CodeValue></dd></div>
                <div><dt>Region</dt><dd><CodeValue>{verification.data.region}</CodeValue></dd></div>
                <div><dt>Verified</dt><dd><time dateTime={verification.data.verifiedAt}>{verification.data.verifiedAt}</time></dd></div>
              </dl>
              <MissingCapabilities capabilities={verification.data.missingCapabilities} />
            </section>
          ) : null}
        </div>
      </section>
    </PageScaffold>
  )
}
