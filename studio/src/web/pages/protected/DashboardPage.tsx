import { useState } from 'react'
import type {
  ListLiveRunsResponse,
  LiveRunSummary,
  LiveSourceProgress,
  RunState,
  SourceId,
} from '../../contracts.generated'

import { CodeValue, Metric, PageScaffold, StatePanel } from './PageScaffold'
import type { ResourceState } from './state'

const SOURCE_ORDER: readonly SourceId[] = ['jde', 'maxdb', 'btrieve']
const SOURCE_LABELS: Readonly<Record<SourceId, string>> = {
  jde: 'JD Edwards World',
  maxdb: 'SAP ERP',
  btrieve: 'Sage ERP',
}

const STATE_LABELS: Readonly<Record<RunState, string>> = {
  created: 'Created',
  inventorying: 'Inventorying',
  redacting: 'Protecting',
  planning: 'Planning',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  executing: 'Executing',
  verifying: 'Verifying',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function stateTone(state: RunState): 'success' | 'danger' | 'warning' | 'active' | 'neutral' {
  if (state === 'completed' || state === 'approved') return 'success'
  if (state === 'failed' || state === 'cancelled') return 'danger'
  if (state === 'awaiting_approval') return 'warning'
  if (state === 'created') return 'neutral'
  return 'active'
}

function StatePill({ state }: { readonly state: RunState }) {
  return <span className={`protected-pill protected-pill--${stateTone(state)}`}>{STATE_LABELS[state]}</span>
}

function SourceSummary({
  sourceId,
  source,
  runId,
  onOpenSource,
}: {
  readonly sourceId: SourceId
  readonly source?: LiveSourceProgress
  readonly runId: string
  readonly onOpenSource?: (runId: string, sourceId: SourceId) => void
}) {
  const content = (
    <>
      <span className="dashboard-source__heading">
        <strong>{SOURCE_LABELS[sourceId]}</strong>
        {source ? <StatePill state={source.state} /> : <span className="protected-pill">Not reported</span>}
      </span>
      {source ? (
        <>
          <CodeValue>{source.hostname}</CodeValue>
          <dl className="dashboard-source__counts">
            <Metric label="Read" value={source.recordsRead.toLocaleString()} />
            <Metric label="Written" value={source.recordsWritten.toLocaleString()} />
            <Metric label="Rejected" value={source.recordsRejected.toLocaleString()} />
          </dl>
          {source.failureCode ? <span className="protected-error-code">{source.failureCode}</span> : null}
        </>
      ) : (
        <p>No authenticated source snapshot was returned.</p>
      )}
    </>
  )

  return onOpenSource ? (
    <article className="dashboard-source dashboard-source--interactive">
      <button
        className="dashboard-source__hitbox"
        type="button"
        onClick={() => onOpenSource(runId, sourceId)}
        aria-label={`Open ${SOURCE_LABELS[sourceId]} for ${runId}`}
      />
      <div className="dashboard-source__content">{content}</div>
    </article>
  ) : <article className="dashboard-source">{content}</article>
}

function RunCard({
  run,
  onOpenRun,
  onOpenSource,
}: {
  readonly run: LiveRunSummary
  readonly onOpenRun?: (runId: string) => void
  readonly onOpenSource?: (runId: string, sourceId: SourceId) => void
}) {
  const bySource = new Map(run.sources.map((source) => [source.sourceId, source]))
  const exactPortfolio = run.sources.length === SOURCE_ORDER.length &&
    SOURCE_ORDER.every((sourceId) => run.sources.filter((source) => source.sourceId === sourceId).length === 1)

  return (
    <article className={`dashboard-run${onOpenRun ? ' dashboard-run--interactive' : ''}`}>
      {onOpenRun ? (
        <button
          className="dashboard-run__hitbox"
          type="button"
          aria-label={`Open mission control for ${run.portfolioName}`}
          onClick={() => onOpenRun(run.runId)}
        />
      ) : null}
      <SealedEvidenceRunner />
      <header className="dashboard-run__header">
        <div>
          <div className="dashboard-run__title-row">
            <h2>{run.portfolioName}</h2>
            <StatePill state={run.state} />
          </div>
          <p className="dashboard-run__identity" aria-label={`Owned by ${run.owner.displayName}, ${run.owner.email}`}>
            Owned by <strong>{run.owner.displayName}</strong> · {run.owner.email}
          </p>
        </div>
      </header>

      <dl className="dashboard-run__facts">
        <Metric label="Run ID" value={<CodeValue>{run.runId}</CodeValue>} />
        <Metric label="Mode" value="Live · private" />
        <Metric label="Updated" value={<time dateTime={run.updatedAt}>{run.updatedAt}</time>} />
        <Metric
          label="Plan digest"
          value={run.portfolioPlanDigest ? <CodeValue>{run.portfolioPlanDigest}</CodeValue> : 'Not published'}
        />
      </dl>

      {!exactPortfolio ? (
        <p className="protected-inline-alert" role="alert">
          This run does not contain exactly one authenticated snapshot for each required source.
        </p>
      ) : null}

      <div className="dashboard-run__sources" aria-label="Required three-source portfolio">
        {SOURCE_ORDER.map((sourceId) => (
          <SourceSummary
            key={sourceId}
            sourceId={sourceId}
            source={bySource.get(sourceId)}
            runId={run.runId}
            onOpenSource={onOpenSource}
          />
        ))}
      </div>
    </article>
  )
}

export interface DashboardPageProps {
  readonly runs: ResourceState<ListLiveRunsResponse>
  readonly onRetry?: () => void
  readonly onCreateRun?: () => void
  readonly onOpenRun?: (runId: string) => void
  readonly onOpenSource?: (runId: string, sourceId: SourceId) => void
}


type EvidenceChecks = { jdeInvalidCyyddd?: number; axOrphanDerived?: number; ebsUnmappedFlexfield?: number }

function SealedEvidenceRunner() {
  const [status, setStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [checks, setChecks] = useState<EvidenceChecks | null>(null)
  const [detail, setDetail] = useState<string | null>(null)

  const start = async () => {
    setStatus('running'); setChecks(null); setDetail(null)
    try {
      const res = await fetch('/api/local-cartridge/v1/evidence-runs', { method: 'POST', cache: 'no-store' })
      if (!res.ok) throw new Error(`agent returned ${res.status}`)
      for (let i = 0; i < 150; i += 1) {
        await new Promise((r) => setTimeout(r, 2000))
        const poll = await fetch('/api/local-cartridge/v1/evidence-runs/current', { cache: 'no-store' })
        const body = await poll.json()
        if (body.status === 'succeeded') { setChecks(body.result?.checks ?? null); setStatus('done'); return }
        if (body.status === 'failed') { setDetail(body.detail ?? 'evidence run failed'); setStatus('error'); return }
      }
      setDetail('timed out waiting for the sealed agent'); setStatus('error')
    } catch (error) {
      setDetail(error instanceof Error ? error.message : 'unreachable'); setStatus('error')
    }
  }

  return (
    <section className="sealed-runner">
      <div className="sealed-runner__bar">
        <div>
          <h3>Sealed sandbox evidence pass</h3>
          <p>Runs the three source emulators on an internal-only network. Count-only output; no raw records leave the sandbox.</p>
        </div>
        <button type="button" className="sealed-runner__play" onClick={() => void start()} disabled={status === 'running'}>
          {status === 'running' ? 'Running…' : '▶  Run JDE · AX · EBS'}
        </button>
      </div>
      {status === 'running' ? <p className="sealed-runner__note">Building images, waiting for source health, certifying count-only guardrails…</p> : null}
      {status === 'error' ? <p className="sealed-runner__err">Evidence run failed: {detail}</p> : null}
      {status === 'done' && checks ? (
        <dl className="sealed-runner__results">
          <div><dt>JDE · invalid CYYDDD</dt><dd>{checks.jdeInvalidCyyddd ?? 0}</dd></div>
          <div><dt>AX · orphan-derived RecId</dt><dd>{checks.axOrphanDerived ?? 0}</dd></div>
          <div><dt>EBS · unmapped flexfield</dt><dd>{checks.ebsUnmappedFlexfield ?? 0}</dd></div>
        </dl>
      ) : null}
    </section>
  )
}

export function DashboardPage({ runs, onRetry, onCreateRun, onOpenRun, onOpenSource }: DashboardPageProps) {
  return (
    <PageScaffold
      eyebrow="Private portfolio"
      title="Mission Control"
      description="Owned migrations stay bound to the authenticated operator and move as an exact three-source portfolio."
      connection={runs.connection}
      stale={runs.stale}
      lastUpdatedAt={runs.lastUpdatedAt}
      actions={onCreateRun ? (
        <button className="protected-button protected-button--primary" type="button" onClick={onCreateRun}>
          Add source portfolio
        </button>
      ) : undefined}
    >
      {runs.status === 'loading' ? (
        <StatePanel kind="loading" title="Loading owned migrations" message="Waiting for an authenticated portfolio response." />
      ) : null}
      {runs.status === 'error' ? (
        <StatePanel kind="error" title="Owned migrations unavailable" message={runs.message} onRetry={onRetry} />
      ) : null}
      {runs.status === 'empty' || (runs.status === 'ready' && runs.data.runs.length === 0) ? (
        <StatePanel
          kind="empty"
          title="No owned migrations yet"
          message={runs.status === 'empty' && runs.message ? runs.message : 'Create a three-source portfolio when your cloud connection is verified.'}
        />
      ) : null}
      {runs.status === 'ready' && runs.data.runs.length > 0 ? (
        <section className="dashboard-runs" aria-label="Owned migrations">
          {runs.data.runs.map((run) => (
            <RunCard key={run.runId} run={run} onOpenRun={onOpenRun} onOpenSource={onOpenSource} />
          ))}
        </section>
      ) : null}
    </PageScaffold>
  )
}
