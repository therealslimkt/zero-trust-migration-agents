import type { FormEvent } from 'react'
import type {
  CloudConnectionResponse,
  DriverApprovalResponse,
  DriverCandidate,
  DriverResearchRequest,
  DriverResearchStatusResponse,
} from '../../contracts.generated'

import { CodeValue, PageScaffold, StatePanel } from './PageScaffold'
import type { ResourceState } from './state'

function ResearchStatus({ state }: { readonly state: DriverResearchStatusResponse }) {
  if (state.status === 'queued' || state.status === 'running') {
    return (
      <section className="protected-operation" aria-live="polite" aria-busy="true">
        <span className="protected-operation__signal" aria-hidden="true" />
        <div>
          <h2>{state.status === 'queued' ? 'Research queued' : 'Research in progress'}</h2>
          <p>
            Gemini is evaluating official driver sources in the selected Google Cloud project.
            No completion percentage is available.
          </p>
          <p><CodeValue>{state.researchId}</CodeValue> · updated <time dateTime={state.updatedAt}>{state.updatedAt}</time></p>
        </div>
      </section>
    )
  }

  if (state.status === 'failed') {
    return (
      <section className="protected-state protected-state--error" role="alert">
        <div>
          <h2>Driver research failed</h2>
          <p>The service returned failure code <CodeValue>{state.failureCode ?? 'unspecified'}</CodeValue>.</p>
        </div>
      </section>
    )
  }

  if (!state.result) {
    return (
      <StatePanel
        kind="error"
        title="Completed response is incomplete"
        message="No structured research result accompanied the completed status."
      />
    )
  }

  return null
}

function CandidateCard({
  candidate,
  approval,
  busy,
  onApprove,
  onManualUpload,
}: {
  readonly candidate: DriverCandidate
  readonly approval?: DriverApprovalResponse
  readonly busy?: boolean
  readonly onApprove?: (candidate: DriverCandidate) => void
  readonly onManualUpload?: (candidate: DriverCandidate) => void
}) {
  const selected = approval?.candidateId === candidate.candidateId
  const needsManualUpload = candidate.redistribution !== 'allowed' ||
    (selected && approval?.retrievalMode === 'manual_vendor_upload')

  return (
    <article className={`driver-candidate${selected ? ' driver-candidate--selected' : ''}`}>
      <header>
        <div>
          <p className="protected-kicker">{candidate.candidateId}</p>
          <h3><CodeValue>{candidate.coordinates}</CodeValue></h3>
          <p>Version {candidate.version}</p>
        </div>
        <span className="protected-confidence" aria-label={`${Math.round(candidate.confidence * 100)} percent confidence`}>
          {Math.round(candidate.confidence * 100)}%
        </span>
      </header>
      <dl className="protected-definition-grid">
        <div><dt>Official source</dt><dd>{candidate.officialSource}</dd></div>
        <div><dt>Compatibility</dt><dd>{candidate.compatibility}</dd></div>
        <div><dt>License</dt><dd>{candidate.license}</dd></div>
        <div><dt>Redistribution</dt><dd>{candidate.redistribution}</dd></div>
        <div><dt>Checksum</dt><dd>{candidate.checksumAvailable ? 'Available' : 'Not reported'}</dd></div>
        <div><dt>Signature</dt><dd>{candidate.signatureAvailable ? 'Available' : 'Not reported'}</dd></div>
      </dl>
      {candidate.caveats.length > 0 ? (
        <div className="driver-candidate__caveats">
          <strong>Caveats</strong>
          <ul>{candidate.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul>
        </div>
      ) : null}
      {selected ? (
        <p className="protected-inline-success" role="status">
          Selection {approval.status}; retrieval mode {approval.retrievalMode}.
          {approval.artifactFingerprint ? <> Fingerprint <CodeValue>{approval.artifactFingerprint}</CodeValue>.</> : null}
        </p>
      ) : null}
      <div className="driver-candidate__actions">
        {onApprove && !selected ? (
          <button className="protected-button protected-button--primary" type="button" disabled={busy} onClick={() => onApprove(candidate)}>
            Approve immutable candidate
          </button>
        ) : null}
        {needsManualUpload && onManualUpload ? (
          <button className="protected-button protected-button--secondary" type="button" disabled={busy} onClick={() => onManualUpload(candidate)}>
            Use vendor upload path
          </button>
        ) : null}
      </div>
    </article>
  )
}

export interface SourceOnboardingPageProps {
  readonly cloud: ResourceState<CloudConnectionResponse>
  readonly request: DriverResearchRequest
  readonly research: ResourceState<DriverResearchStatusResponse>
  readonly approval?: DriverApprovalResponse
  readonly submitting?: boolean
  readonly onRequestChange: (request: DriverResearchRequest) => void
  readonly onStartResearch?: (request: DriverResearchRequest) => void
  readonly onApproveCandidate?: (candidate: DriverCandidate) => void
  readonly onManualUpload?: (candidate: DriverCandidate) => void
  readonly onRetry?: () => void
  readonly onOpenCloudSettings?: () => void
}

export function SourceOnboardingPage({
  cloud,
  request,
  research,
  approval,
  submitting = false,
  onRequestChange,
  onStartResearch,
  onApproveCandidate,
  onManualUpload,
  onRetry,
  onOpenCloudSettings,
}: SourceOnboardingPageProps) {
  const cloudVerified = cloud.status === 'ready' && cloud.data.status === 'verified'
  const completedResult = research.status === 'ready' && research.data.status === 'completed'
    ? research.data.result
    : undefined

  const update = <Key extends keyof DriverResearchRequest>(key: Key, value: DriverResearchRequest[Key]) => {
    onRequestChange({ ...request, [key]: value })
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (cloudVerified && onStartResearch) onStartResearch(request)
  }

  return (
    <PageScaffold
      eyebrow="Source onboarding"
      title="Research a JDBC driver"
      description="Research runs asynchronously in your connected Google Cloud project. Every candidate remains review-only until a human approves its exact evidence digest."
      connection={research.connection}
      stale={research.stale}
      lastUpdatedAt={research.lastUpdatedAt}
    >
      <section className="protected-step" aria-labelledby="cloud-check-heading">
        <div className="protected-step__number">01</div>
        <div className="protected-step__content">
          <h2 id="cloud-check-heading">Confirm cloud connection</h2>
          {cloud.status === 'loading' ? <p role="status">Checking the authenticated cloud connection…</p> : null}
          {cloud.status === 'error' ? <p role="alert">{cloud.message}</p> : null}
          {cloud.status === 'empty' ? <p>No cloud connection has been configured.</p> : null}
          {cloud.status === 'ready' ? (
            <p>
              Status <strong>{cloud.data.status}</strong>
              {cloud.data.projectId ? <> · project <CodeValue>{cloud.data.projectId}</CodeValue></> : null}
              {cloud.data.region ? <> · region <CodeValue>{cloud.data.region}</CodeValue></> : null}
            </p>
          ) : null}
          {!cloudVerified && onOpenCloudSettings ? (
            <button className="protected-button protected-button--secondary" type="button" onClick={onOpenCloudSettings}>
              Open cloud settings
            </button>
          ) : null}
        </div>
      </section>

      <section className="protected-step" aria-labelledby="source-profile-heading">
        <div className="protected-step__number">02</div>
        <div className="protected-step__content">
          <h2 id="source-profile-heading">Describe the source runtime</h2>
          <form className="protected-form" onSubmit={submit}>
            <label>Google Cloud project<input required value={request.projectId} onChange={(event) => update('projectId', event.target.value)} /></label>
            <label>Database family<input required value={request.databaseFamily} onChange={(event) => update('databaseFamily', event.target.value)} /></label>
            <label>Database version<input required value={request.databaseVersion} onChange={(event) => update('databaseVersion', event.target.value)} /></label>
            <label>Application layer<input required value={request.applicationLayer} onChange={(event) => update('applicationLayer', event.target.value)} /></label>
            <label>Java runtime<input required value={request.javaRuntime} onChange={(event) => update('javaRuntime', event.target.value)} /></label>
            <label>
              Connectivity mode
              <select value={request.connectivityMode} onChange={(event) => update('connectivityMode', event.target.value as DriverResearchRequest['connectivityMode'])}>
                <option value="tailscale">Tailscale</option>
                <option value="private_service_connect">Private Service Connect</option>
                <option value="vpn">VPN</option>
              </select>
            </label>
            <label className="protected-form__wide">Official repository (optional)<input value={request.officialRepository ?? ''} onChange={(event) => update('officialRepository', event.target.value || undefined)} /></label>
            <div className="protected-form__actions protected-form__wide">
              <button className="protected-button protected-button--primary" type="submit" disabled={!cloudVerified || submitting || !onStartResearch}>
                {submitting ? 'Submitting research…' : 'Start Gemini research'}
              </button>
              {!cloudVerified ? <span>Verify the cloud connection before research can start.</span> : null}
            </div>
          </form>
        </div>
      </section>

      <section className="protected-step" aria-labelledby="research-heading">
        <div className="protected-step__number">03</div>
        <div className="protected-step__content">
          <h2 id="research-heading">Review research evidence</h2>
          {research.status === 'loading' ? <StatePanel kind="loading" title="Loading research state" message="Waiting for a structured status response." /> : null}
          {research.status === 'empty' ? <StatePanel kind="empty" title="No research submitted" message={research.message ?? 'Complete the source profile to begin.'} /> : null}
          {research.status === 'error' ? <StatePanel kind="error" title="Research unavailable" message={research.message} onRetry={onRetry} /> : null}
          {research.status === 'ready' ? <ResearchStatus state={research.data} /> : null}
          {completedResult ? (
            <>
              <div className="protected-research-summary">
                <span>Model <CodeValue>{completedResult.model}</CodeValue></span>
                <span>Evidence <CodeValue>{completedResult.evidenceDigest}</CodeValue></span>
                <span>Created <time dateTime={completedResult.createdAt}>{completedResult.createdAt}</time></span>
              </div>
              {completedResult.candidates.length === 0 ? (
                <StatePanel kind="empty" title="No compatible candidates" message="The completed research returned no driver candidates." />
              ) : (
                <div className="driver-candidates">
                  {completedResult.candidates.map((candidate) => (
                    <CandidateCard
                      key={candidate.candidateId}
                      candidate={candidate}
                      approval={approval}
                      busy={submitting}
                      onApprove={onApproveCandidate}
                      onManualUpload={onManualUpload}
                    />
                  ))}
                </div>
              )}
            </>
          ) : null}
          <aside className="protected-safety-note">
            Restricted drivers use the vendor upload path into your standard repository. The web service does not scrape vendors, bypass licensing, or execute retrieved JARs.
          </aside>
        </div>
      </section>
    </PageScaffold>
  )
}
