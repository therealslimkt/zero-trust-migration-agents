import type { KeyboardEvent } from 'react'
import type {
  CompilerAction,
  DeclarativeTransform,
  EvidenceReference,
  LiveRunEvent,
  LiveSourceResponse,
  NamedValue,
  SchemaField,
  SourceReplay,
  SyntheticValue,
} from '../../contracts.generated'

import { CodeValue, Metric, PageScaffold, StatePanel } from './PageScaffold'
import type { ResourceState } from './state'

export type SourcePane = 'source' | 'plan' | 'evidence'

const PANES: ReadonlyArray<{ readonly id: SourcePane; readonly label: string }> = [
  { id: 'source', label: 'Source & schema' },
  { id: 'plan', label: 'Plan & diff' },
  { id: 'evidence', label: 'Evidence & timeline' },
]

function displayValue(value: SyntheticValue): string {
  if (value === null) return 'null'
  return String(value)
}

function SchemaTable({ fields, label }: { readonly fields: readonly SchemaField[]; readonly label: string }) {
  return (
    <div className="protected-table-scroll">
      <table className="protected-table">
        <caption>{label}</caption>
        <thead><tr><th scope="col">Field</th><th scope="col">Type</th><th scope="col">Nullable</th><th scope="col">Description</th></tr></thead>
        <tbody>
          {fields.map((field) => (
            <tr key={`${field.name}:${field.dataType}`}>
              <th scope="row"><CodeValue>{field.name}</CodeValue></th>
              <td>{field.dataType}</td>
              <td>{field.nullable ? 'Yes' : 'No'}</td>
              <td>{field.description ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ValuesTable({ values, label }: { readonly values: readonly NamedValue[]; readonly label: string }) {
  return (
    <table className="protected-table protected-table--compact">
      <caption>{label}</caption>
      <thead><tr><th scope="col">Field</th><th scope="col">Type</th><th scope="col">Value</th></tr></thead>
      <tbody>
        {values.map((field) => (
          <tr key={`${field.name}:${field.dataType}`}>
            <th scope="row">{field.name}</th>
            <td>{field.dataType}</td>
            <td><CodeValue>{displayValue(field.value)}</CodeValue></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function EvidenceList({ evidence }: { readonly evidence: readonly EvidenceReference[] }) {
  if (evidence.length === 0) return <p className="protected-muted">No evidence references were returned.</p>
  return (
    <ul className="source-evidence-list">
      {evidence.map((item) => (
        <li key={`${item.artifactId}:${item.digest}`}>
          <span>{item.kind}</span>
          <CodeValue>{item.artifactId}</CodeValue>
          <CodeValue>{item.digest}</CodeValue>
        </li>
      ))}
    </ul>
  )
}

function QueryList({ queries, onCopy }: { readonly queries: readonly string[]; readonly onCopy?: (query: string) => void }) {
  if (queries.length === 0) return <p className="protected-muted">No example queries were returned.</p>
  return (
    <div className="source-query-list">
      {queries.map((query) => (
        <div key={query} className="source-query">
          <pre tabIndex={0}><code>{query}</code></pre>
          {onCopy ? <button type="button" className="protected-button protected-button--quiet" onClick={() => onCopy(query)}>Copy</button> : null}
        </div>
      ))}
    </div>
  )
}

function SourcePaneContent({ replay, onCopy }: { readonly replay: SourceReplay; readonly onCopy?: (value: string) => void }) {
  return (
    <>
      <section className="source-pane__section">
        <h3>Source identity</h3>
        <dl className="protected-definition-grid">
          <div><dt>Hostname</dt><dd><CodeValue>{replay.hostname}</CodeValue></dd></div>
          <div><dt>Database</dt><dd>{replay.source.databaseFamily} {replay.source.databaseVersion}</dd></div>
          <div><dt>Application</dt><dd>{replay.source.applicationLayer}</dd></div>
          <div><dt>Source ID</dt><dd><CodeValue>{replay.sourceId}</CodeValue></dd></div>
        </dl>
      </section>
      <section className="source-pane__section">
        <h3>Source schema</h3>
        <SchemaTable fields={replay.source.schema} label={`${replay.displayName} source schema`} />
      </section>
      <section className="source-pane__section">
        <h3>Authenticated synthetic samples</h3>
        {replay.source.samples.length === 0 ? <p className="protected-muted">No samples were returned for this source.</p> : (
          <div className="source-samples">
            {replay.source.samples.map((sample) => (
              <article key={sample.recordId} className="source-sample">
                <header>
                  <strong>{sample.recordId}</strong>
                  {onCopy ? <button className="protected-button protected-button--quiet" type="button" onClick={() => onCopy(sample.rawBytesHex)}>Copy raw hex</button> : null}
                </header>
                <p>Raw bytes <CodeValue>{sample.rawBytesHex}</CodeValue></p>
                <ValuesTable values={sample.decodedFields} label={`Decoded fields for ${sample.recordId}`} />
              </article>
            ))}
          </div>
        )}
      </section>
      <section className="source-pane__section">
        <h3>Read-only example queries</h3>
        <QueryList queries={replay.source.exampleQueries} onCopy={onCopy} />
        <p className="protected-muted">The browser does not open an arbitrary source shell.</p>
      </section>
    </>
  )
}

function TransformTable({ transforms }: { readonly transforms: readonly DeclarativeTransform[] }) {
  return (
    <div className="protected-table-scroll">
      <table className="protected-table">
        <caption>Ordered declarative transforms</caption>
        <thead><tr><th scope="col">#</th><th scope="col">Operation</th><th scope="col">Source</th><th scope="col">Target</th><th scope="col">Parameters</th></tr></thead>
        <tbody>
          {transforms.map((transform) => {
            const parameters = [transform.encoding, transform.targetType, transform.format].filter(Boolean).join(' · ')
            return (
              <tr key={transform.sequence}>
                <td>{transform.sequence}</td>
                <td>{transform.operation}</td>
                <td><CodeValue>{transform.sourceField}</CodeValue></td>
                <td><CodeValue>{transform.targetField}</CodeValue></td>
                <td>{parameters || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ActionTimeline({ actions }: { readonly actions: readonly CompilerAction[] }) {
  if (actions.length === 0) return <p className="protected-muted">No compiler actions were returned.</p>
  return (
    <ol className="source-timeline">
      {actions.map((action) => (
        <li key={action.eventId}>
          <div className="source-timeline__marker">{action.sequence}</div>
          <div>
            <header><strong>{action.summary}</strong><span>{action.stage}</span></header>
            <p>{action.agent} · {action.tool}</p>
            <p>{action.result}</p>
            <time dateTime={action.timestamp}>{action.timestamp}</time>
            <EvidenceList evidence={action.evidenceReferences} />
          </div>
        </li>
      ))}
    </ol>
  )
}

function PlanPaneContent({ replay }: { readonly replay: SourceReplay }) {
  const compiler = replay.compiler
  return (
    <>
      <section className="source-pane__section">
        <h3>Observable compiler actions</h3>
        <p className="protected-muted">Tool actions and results are shown; private model chain-of-thought is not collected or displayed.</p>
        <ActionTimeline actions={compiler.actions} />
      </section>
      <section className="source-pane__section">
        <h3>Declarative plan diff</h3>
        <TransformTable transforms={compiler.transforms} />
      </section>
      <section className="source-pane__section">
        <h3>Selected driver</h3>
        <dl className="protected-definition-grid">
          <div><dt>Coordinates</dt><dd><CodeValue>{compiler.driver.coordinates}</CodeValue></dd></div>
          <div><dt>Version</dt><dd>{compiler.driver.version}</dd></div>
          <div><dt>Official source</dt><dd>{compiler.driver.sourceUrl}</dd></div>
          <div><dt>License</dt><dd>{compiler.driver.license}</dd></div>
          <div><dt>SHA-256</dt><dd><CodeValue>{compiler.driver.sha256}</CodeValue></dd></div>
          <div><dt>Signature</dt><dd>{compiler.driver.signatureVerified ? 'Verified' : 'Not verified'}</dd></div>
        </dl>
      </section>
      <section className="source-pane__section">
        <h3>Execution binding</h3>
        <dl className="protected-definition-grid">
          <div><dt>Approval</dt><dd>{compiler.approval.decision} · <time dateTime={compiler.approval.decidedAt}>{compiler.approval.decidedAt}</time></dd></div>
          <div><dt>Plan digest</dt><dd><CodeValue>{compiler.approval.planDigest}</CodeValue></dd></div>
          <div><dt>Dataflow job</dt><dd><CodeValue>{compiler.dataflowJobId}</CodeValue></dd></div>
          <div><dt>Beam transforms</dt><dd>{compiler.beamTransformIds.map((id) => <CodeValue key={id}>{id}</CodeValue>)}</dd></div>
        </dl>
        <EvidenceList evidence={[compiler.localGemmaEvidence, compiler.geminiVertexEvidence]} />
      </section>
    </>
  )
}

function EventTimeline({ events }: { readonly events: readonly LiveRunEvent[] }) {
  if (events.length === 0) return <p className="protected-muted">No persisted events were returned.</p>
  return (
    <ol className="source-timeline source-timeline--events">
      {events.map((event) => (
        <li key={event.eventId}>
          <div className="source-timeline__marker">{event.sequence}</div>
          <div>
            <header><strong>{event.summary}</strong><span>{event.state}</span></header>
            <p>{event.eventType}</p>
            <time dateTime={event.timestamp}>{event.timestamp}</time>
            <EvidenceList evidence={event.evidenceReferences} />
          </div>
        </li>
      ))}
    </ol>
  )
}

function EvidencePaneContent({ replay, events, onCopy }: { readonly replay: SourceReplay; readonly events: readonly LiveRunEvent[]; readonly onCopy?: (value: string) => void }) {
  const destination = replay.destination
  const reconciliation = destination.reconciliation
  return (
    <>
      <section className="source-pane__section">
        <h3>BigQuery destination</h3>
        <p><CodeValue>{destination.dataset}.{destination.table}</CodeValue></p>
        <SchemaTable fields={destination.schema} label="Destination schema" />
      </section>
      <section className="source-pane__section">
        <h3>Transformed synthetic rows</h3>
        {destination.rows.length === 0 ? <p className="protected-muted">No destination rows were returned.</p> : (
          <div className="source-samples">
            {destination.rows.map((row) => <ValuesTable key={row.recordId} values={row.fields} label={`Destination row ${row.recordId}`} />)}
          </div>
        )}
      </section>
      <section className={`source-reconciliation source-reconciliation--${reconciliation.status}`}>
        <h3>Reconciliation {reconciliation.status}</h3>
        <dl className="source-reconciliation__metrics">
          <Metric label="Read" value={reconciliation.recordsRead.toLocaleString()} />
          <Metric label="Written" value={reconciliation.recordsWritten.toLocaleString()} />
          <Metric label="Rejected" value={reconciliation.recordsRejected.toLocaleString()} />
          <Metric label="Output rows" value={reconciliation.outputRows.toLocaleString()} />
        </dl>
        <p>Source checksum <CodeValue>{reconciliation.sourceChecksum}</CodeValue></p>
        <p>Destination checksum <CodeValue>{reconciliation.destinationChecksum}</CodeValue></p>
        <EvidenceList evidence={[reconciliation.evidence, destination.dataflowEvidence, destination.bigQueryEvidence]} />
      </section>
      <section className="source-pane__section">
        <h3>Persisted event timeline</h3>
        <EventTimeline events={events} />
      </section>
      <section className="source-pane__section">
        <h3>Suggested BigQuery SQL</h3>
        <QueryList queries={destination.suggestedQueries} onCopy={onCopy} />
      </section>
    </>
  )
}

function tabletVisible(active: SourcePane, pane: SourcePane): boolean {
  if (active === 'evidence') return pane !== 'source'
  return pane !== 'evidence'
}

function ProgressOnlyPanes({ source, events, activePane }: { readonly source: LiveSourceResponse; readonly events: readonly LiveRunEvent[]; readonly activePane: SourcePane }) {
  const progress = source.progress
  return (
    <div className="source-three-pane">
      <section id="source-panel-source" className="source-pane source-pane--source" role="tabpanel" aria-labelledby="source-tab-source" data-active={activePane === 'source'} data-tablet-visible={tabletVisible(activePane, 'source')}>
        <header><span>01</span><h2>Source system / Google VM</h2></header>
        <section className="source-pane__section">
          <h3>Authenticated source snapshot</h3>
          <dl className="protected-definition-grid">
            <div><dt>Source ID</dt><dd><CodeValue>{source.sourceId}</CodeValue></dd></div>
            <div><dt>Hostname</dt><dd><CodeValue>{source.hostname}</CodeValue></dd></div>
            <div><dt>State</dt><dd>{source.state}</dd></div>
            <div><dt>Snapshot</dt><dd>{source.snapshotVersion}</dd></div>
          </dl>
          <p className="protected-muted">Schema and sample artifacts have not been captured for this run. The authenticated counters remain visible.</p>
        </section>
      </section>
      <section id="source-panel-plan" className="source-pane source-pane--plan" role="tabpanel" aria-labelledby="source-tab-plan" data-active={activePane === 'plan'} data-tablet-visible={tabletVisible(activePane, 'plan')}>
        <header><span>02</span><h2>Agentic compiler middleware</h2></header>
        <section className="source-pane__section">
          <h3>Persisted plan state</h3>
          <p>Plan digest {progress.planDigest ? <CodeValue>{progress.planDigest}</CodeValue> : 'not published'}</p>
          <p className="protected-muted">Compiler actions and transform artifacts were not captured as source-detail data for this run.</p>
          <EvidenceList evidence={progress.evidenceReferences} />
        </section>
      </section>
      <section id="source-panel-evidence" className="source-pane source-pane--evidence" role="tabpanel" aria-labelledby="source-tab-evidence" data-active={activePane === 'evidence'} data-tablet-visible={tabletVisible(activePane, 'evidence')}>
        <header><span>03</span><h2>BigQuery evidence</h2></header>
        <section className="source-pane__section">
          <h3>Persisted source evidence</h3>
          <EvidenceList evidence={progress.evidenceReferences} />
        </section>
        <section className="source-pane__section">
          <h3>Persisted event timeline</h3>
          <EventTimeline events={events} />
        </section>
        <section className="source-pane__section">
          <h3>Destination status</h3>
          <p>{progress.recordsWritten > 0 ? `${progress.recordsWritten.toLocaleString()} records reported written.` : 'No verified destination writes have been reported.'}</p>
        </section>
      </section>
    </div>
  )
}

export interface SourceDetailPageProps {
  readonly source: ResourceState<LiveSourceResponse>
  readonly events?: readonly LiveRunEvent[]
  readonly activePane: SourcePane
  readonly onActivePaneChange: (pane: SourcePane) => void
  readonly onRetry?: () => void
  readonly onCopy?: (value: string) => void
}

export function SourceDetailPage({ source, events = [], activePane, onActivePaneChange, onRetry, onCopy }: SourceDetailPageProps) {
  const ready = source.status === 'ready' ? source.data : undefined
  const replay = ready?.detail
  const relevantEvents = ready
    ? events.filter((event) => event.sourceId === undefined || event.sourceId === ready.sourceId)
    : []

  const movePaneFocus = (event: KeyboardEvent<HTMLButtonElement>, paneIndex: number) => {
    let nextIndex: number | undefined
    if (event.key === 'ArrowRight') nextIndex = (paneIndex + 1) % PANES.length
    if (event.key === 'ArrowLeft') nextIndex = (paneIndex - 1 + PANES.length) % PANES.length
    if (event.key === 'Home') nextIndex = 0
    if (event.key === 'End') nextIndex = PANES.length - 1
    if (nextIndex === undefined) return
    event.preventDefault()
    const nextPane = PANES[nextIndex]
    onActivePaneChange(nextPane.id)
    document.getElementById(`source-tab-${nextPane.id}`)?.focus()
  }

  return (
    <PageScaffold
      eyebrow={ready ? `Run ${ready.runId}` : 'Live source'}
      title={replay?.displayName ?? ready?.sourceId ?? 'Source detail'}
      description={ready ? `${ready.hostname} · authenticated snapshot ${ready.snapshotVersion}` : 'Source, plan, and evidence from one authenticated run.'}
      connection={source.connection}
      stale={source.stale}
      lastUpdatedAt={source.lastUpdatedAt ?? ready?.updatedAt}
    >
      {source.status === 'loading' ? <StatePanel kind="loading" title="Loading source detail" message="Waiting for the authenticated source snapshot." /> : null}
      {source.status === 'empty' ? <StatePanel kind="empty" title="No source detail" message={source.message ?? 'No source snapshot was returned.'} /> : null}
      {source.status === 'error' ? <StatePanel kind="error" title="Source detail unavailable" message={source.message} onRetry={onRetry} /> : null}
      {ready ? (
        <>
          <section className="source-context" aria-label="Pinned source context">
            <dl>
              <Metric label="State" value={ready.state} />
              <Metric label="Source" value={<CodeValue>{ready.sourceId}</CodeValue>} />
              <Metric label="Hostname" value={<CodeValue>{ready.hostname}</CodeValue>} />
              <Metric label="Read" value={ready.progress.recordsRead.toLocaleString()} />
              <Metric label="Written" value={ready.progress.recordsWritten.toLocaleString()} />
              <Metric label="Rejected" value={ready.progress.recordsRejected.toLocaleString()} />
            </dl>
            {ready.progress.failureCode ? <p className="protected-inline-alert" role="alert">Failure code <CodeValue>{ready.progress.failureCode}</CodeValue></p> : null}
          </section>

          <div className="source-pane-tabs" role="tablist" aria-label="Source detail panes">
                {PANES.map((pane, paneIndex) => (
                  <button
                    key={pane.id}
                    id={`source-tab-${pane.id}`}
                    className="source-pane-tab"
                    type="button"
                    role="tab"
                    aria-selected={activePane === pane.id}
                    aria-controls={`source-panel-${pane.id}`}
                    tabIndex={activePane === pane.id ? 0 : -1}
                    onClick={() => onActivePaneChange(pane.id)}
                    onKeyDown={(event) => movePaneFocus(event, paneIndex)}
                  >
                    {pane.label}
                  </button>
                ))}
          </div>
          {!replay ? (
            <ProgressOnlyPanes source={ready} events={relevantEvents} activePane={activePane} />
          ) : (
              <div className="source-three-pane">
                <section id="source-panel-source" className="source-pane source-pane--source" role="tabpanel" aria-labelledby="source-tab-source" data-active={activePane === 'source'} data-tablet-visible={tabletVisible(activePane, 'source')}>
                  <header><span>01</span><h2>Source system / Google VM</h2></header>
                  <SourcePaneContent replay={replay} onCopy={onCopy} />
                </section>
                <section id="source-panel-plan" className="source-pane source-pane--plan" role="tabpanel" aria-labelledby="source-tab-plan" data-active={activePane === 'plan'} data-tablet-visible={tabletVisible(activePane, 'plan')}>
                  <header><span>02</span><h2>Agentic compiler middleware</h2></header>
                  <PlanPaneContent replay={replay} />
                </section>
                <section id="source-panel-evidence" className="source-pane source-pane--evidence" role="tabpanel" aria-labelledby="source-tab-evidence" data-active={activePane === 'evidence'} data-tablet-visible={tabletVisible(activePane, 'evidence')}>
                  <header><span>03</span><h2>BigQuery evidence</h2></header>
                  <EvidencePaneContent replay={replay} events={relevantEvents} onCopy={onCopy} />
                </section>
              </div>
          )}
        </>
      ) : null}
    </PageScaffold>
  )
}
