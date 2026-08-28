import { useState, type KeyboardEvent, type ReactNode } from 'react'
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
  TerminalLane,
} from '../../contracts.generated'
import jetsonAsset from '../../assets/jetson/jetson-orin-super-pixel.png'
import { TerminalActorLabels, TerminalFrameRenderer, type TerminalFeed } from '../../features/terminal'
import { PixelIcon, TerminalWindow, type PixelIconName, type TerminalAccent } from '../../shared/ui'

import { CodeValue, Metric, PageScaffold, StatePanel } from './PageScaffold'
import type { ResourceState } from './state'

export type SourcePane = 'source' | 'plan' | 'evidence'

const PANES: ReadonlyArray<{ readonly id: SourcePane; readonly label: string }> = [
  { id: 'source', label: 'Source & schema' },
  { id: 'plan', label: 'Plan & diff' },
  { id: 'evidence', label: 'Evidence & timeline' },
]

const EMPTY_TERMINAL_FEED: TerminalFeed = { mode: 'live', frames: [], connection: 'connecting' }

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

function EvidencePaneContent({ replay, events }: { readonly replay: SourceReplay; readonly events: readonly LiveRunEvent[] }) {
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
    </>
  )
}

function CompilerToolCards({ replay }: { readonly replay: SourceReplay }) {
  const tools = Array.from(new Map(replay.compiler.actions.map((action) => [
    `${action.agent}\u0000${action.tool}`,
    { agent: action.agent, tool: action.tool },
  ])).values())
  return (
    <div className="source-tool-cards" aria-label="Captured compiler tools">
      {tools.map((tool) => <span key={`${tool.agent}:${tool.tool}`}><strong>{tool.agent}</strong><small>{tool.tool}</small></span>)}
      <span><strong>{replay.compiler.driver.coordinates}</strong><small>driver {replay.compiler.driver.version}</small></span>
      {replay.compiler.beamTransformIds.map((transform) => <span key={transform}><strong>Apache Beam</strong><small>{transform}</small></span>)}
    </div>
  )
}

interface TerminalPaneProps {
  readonly id: SourcePane
  readonly activePane: SourcePane
  readonly number: string
  readonly title: string
  readonly breadcrumb: string
  readonly icon: PixelIconName
  readonly accent: TerminalAccent
  readonly tools: ReactNode
  readonly lane: TerminalLane
  readonly terminal: TerminalFeed
  readonly maximized: boolean
  readonly obscured: boolean
  readonly onMaximize: (maximized: boolean) => void
  readonly children: ReactNode
}

function TerminalPane({ id, activePane, number, title, breadcrumb, icon, accent, tools, lane, terminal, maximized, obscured, onMaximize, children }: TerminalPaneProps) {
  const latest = terminal.frames.at(-1)
  return (
    <section
      id={`source-panel-${id}`}
      className={`source-pane source-pane--${id}`}
      role="tabpanel"
      aria-labelledby={`source-tab-${id}`}
      data-active={activePane === id}
      data-tablet-visible={tabletVisible(activePane, id)}
      data-maximized={maximized}
      data-obscured={obscured}
      data-stream-active={latest?.lane === lane}
      data-lane={lane}
    >
      <header className="source-pane__label"><span>{number}</span><h2>{title}</h2></header>
      <div className="source-pane__tools">{tools}</div>
      <TerminalWindow
        title={`${title} mirror`}
        breadcrumb={breadcrumb}
        accent={accent}
        icon={<PixelIcon name={icon} size="sm" color={accent} glow />}
        variant="elevated"
        scanlines
        cornerBrackets
        maxHeight="58vh"
        minHeight="480px"
        className="source-pane__terminal"
        bodyClassName="source-pane__terminal-body"
        isMaximized={maximized}
        onMaximize={onMaximize}
        badge={<span className="source-terminal-connection" data-state={terminal.connection}><i />{terminal.connection === 'live' ? 'CONNECTED' : terminal.connection.toUpperCase()}</span>}
        footer={<><span>READ-ONLY MIRROR · EXACT PRODUCER-ADMITTED FRAMES</span><span>{terminal.cursor ?? 'NO CURSOR'}</span></>}
      >
        <TerminalFrameRenderer feed={terminal} lane={lane} label={title} />
      </TerminalWindow>
      <details className="source-pane__details" open>
        <summary>Inspect verified {id === 'source' ? 'source and schema' : id === 'plan' ? 'plan and diff' : 'evidence and timeline'} data</summary>
        {children}
      </details>
    </section>
  )
}

function MissingCapture({ children }: { readonly children: ReactNode }) {
  return <p className="source-capture-note"><PixelIcon name="shield-check" size="xs" color="muted" />{children}</p>
}

function LiveNarration({ event }: { readonly event?: LiveRunEvent }) {
  if (!event) return null
  return (
    <aside className="source-live-narration" aria-live="polite">
      <PixelIcon name="gemini" size="md" color="google-blue" glow />
      <div>
        <span>LIVE RUN NARRATION · EVENT {event.sequence}</span>
        <strong>{event.summary}</strong>
        <small>{event.eventType} · {event.state}</small>
      </div>
    </aside>
  )
}

function tabletVisible(active: SourcePane, pane: SourcePane): boolean {
  if (active === 'evidence') return pane !== 'source'
  return pane !== 'evidence'
}

interface PaneLayoutProps {
  readonly terminal: TerminalFeed
  readonly maximizedPane?: SourcePane
  readonly onMaximizedPaneChange: (pane?: SourcePane) => void
}

function paneLayout(layout: PaneLayoutProps, pane: SourcePane) {
  return {
    terminal: layout.terminal,
    maximized: layout.maximizedPane === pane,
    obscured: layout.maximizedPane !== undefined && layout.maximizedPane !== pane,
    onMaximize: (maximized: boolean) => layout.onMaximizedPaneChange(maximized ? pane : undefined),
  }
}

function EdgeLane({ terminal }: { readonly terminal: TerminalFeed }) {
  const [maximized, setMaximized] = useState(false)
  const latest = terminal.frames.at(-1)
  return (
    <section className="source-edge-lane" data-lane="edge" data-stream-active={latest?.lane === 'edge'} data-maximized={maximized} aria-label="Jetson edge live terminal lane">
      <div className="source-edge-lane__identity">
        <img src={jetsonAsset} alt="Jetson Orin Super edge device" />
        <div><span>JETSON EDGE LANE</span><strong>Private decode + protection boundary</strong><small>Only exact admitted frames are mirrored. Raw credentials and hidden reasoning are never rendered.</small></div>
      </div>
      <div className="source-edge-lane__actors"><TerminalActorLabels frames={terminal.frames} lane="edge" /></div>
      <TerminalWindow
        title="Jetson edge terminal mirror"
        breadcrumb="edge/private-runtime"
        accent="google-red"
        icon={<PixelIcon name="cpu" size="sm" color="google-red" glow />}
        variant="elevated"
        className="source-edge-lane__terminal"
        scanlines
        cornerBrackets
        minHeight={maximized ? '62vh' : '260px'}
        maxHeight={maximized ? '72vh' : '380px'}
        isMaximized={maximized}
        onMaximize={setMaximized}
        badge={<span className="source-terminal-connection" data-state={terminal.connection}><i />{terminal.connection === 'live' ? 'CONNECTED' : terminal.connection.toUpperCase()}</span>}
        bodyClassName="source-pane__terminal-body"
        footer={<><span>PRIVATE EDGE · EXACT SENT / RECEIVED FRAMES</span><span>{terminal.cursor ?? 'NO CURSOR'}</span></>}
      >
        <TerminalFrameRenderer feed={terminal} lane="edge" label="Jetson edge" />
      </TerminalWindow>
    </section>
  )
}

function ProgressOnlyPanes({ source, events, activePane, terminal, maximizedPane, onMaximizedPaneChange }: { readonly source: LiveSourceResponse; readonly events: readonly LiveRunEvent[]; readonly activePane: SourcePane } & PaneLayoutProps) {
  const progress = source.progress
  return (
    <div className="source-three-pane">
      <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange }, 'source')} lane="source" id="source" activePane={activePane} number="01" title="Source system / Google VM" breadcrumb={`${source.hostname}/${source.sourceId}`} icon="compute-engine" accent="google-blue" tools={<MissingCapture>Query capture unavailable for this run</MissingCapture>}>
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
      </TerminalPane>
      <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange }, 'plan')} lane="compiler" id="plan" activePane={activePane} number="02" title="Agentic compiler middleware" breadcrumb={`compiler/${source.sourceId}/events`} icon="apache-beam" accent="google-yellow" tools={<MissingCapture>Compiler tool labels have not been captured for this run</MissingCapture>}>
        <section className="source-pane__section">
          <h3>Persisted plan state</h3>
          <p>Plan digest {progress.planDigest ? <CodeValue>{progress.planDigest}</CodeValue> : 'not published'}</p>
          <p className="protected-muted">Compiler actions and transform artifacts were not captured as source-detail data for this run.</p>
          <EvidenceList evidence={progress.evidenceReferences} />
        </section>
        <section className="source-pane__section">
          <h3>Live translation event feed</h3>
          <EventTimeline events={events} />
        </section>
      </TerminalPane>
      <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange }, 'evidence')} lane="destination" id="evidence" activePane={activePane} number="03" title="Google BigQuery" breadcrumb={`bigquery/${source.sourceId}/verified-writes`} icon="bigquery" accent="google-green" tools={<MissingCapture>Suggested query capture unavailable for this run</MissingCapture>}>
        <section className="source-pane__section">
          <h3>Persisted source evidence</h3>
          <EvidenceList evidence={progress.evidenceReferences} />
        </section>
        <section className="source-pane__section">
          <h3>Destination status</h3>
          <p>{progress.recordsWritten > 0 ? `${progress.recordsWritten.toLocaleString()} records reported written.` : 'No verified destination writes have been reported.'}</p>
        </section>
      </TerminalPane>
    </div>
  )
}

export interface SourceDetailPageProps {
  readonly source: ResourceState<LiveSourceResponse>
  readonly events?: readonly LiveRunEvent[]
  readonly terminal?: TerminalFeed
  readonly activePane: SourcePane
  readonly onActivePaneChange: (pane: SourcePane) => void
  readonly onRetry?: () => void
  readonly onCopy?: (value: string) => void
}

export function SourceDetailPage({ source, events = [], terminal = EMPTY_TERMINAL_FEED, activePane, onActivePaneChange, onRetry, onCopy }: SourceDetailPageProps) {
  const [maximizedPane, setMaximizedPane] = useState<SourcePane>()
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
          <LiveNarration event={relevantEvents.at(-1)} />
          {!replay ? (
            <ProgressOnlyPanes source={ready} events={relevantEvents} activePane={activePane} terminal={terminal} maximizedPane={maximizedPane} onMaximizedPaneChange={setMaximizedPane} />
          ) : (
              <div className="source-three-pane">
                <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange: setMaximizedPane }, 'source')} lane="source" id="source" activePane={activePane} number="01" title="Source system / Google VM" breadcrumb={`${replay.hostname}/${replay.sourceId}`} icon="compute-engine" accent="google-blue" tools={replay.source.exampleQueries.length ? <QueryList queries={replay.source.exampleQueries} onCopy={onCopy} /> : <MissingCapture>No read-only source queries were captured</MissingCapture>}>
                  <SourcePaneContent replay={replay} onCopy={onCopy} />
                </TerminalPane>
                <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange: setMaximizedPane }, 'plan')} lane="compiler" id="plan" activePane={activePane} number="02" title="Agentic compiler middleware" breadcrumb={`compiler/${replay.sourceId}/translations`} icon="apache-beam" accent="google-yellow" tools={<CompilerToolCards replay={replay} />}>
                  <PlanPaneContent replay={replay} />
                </TerminalPane>
                <TerminalPane {...paneLayout({ terminal, maximizedPane, onMaximizedPaneChange: setMaximizedPane }, 'evidence')} lane="destination" id="evidence" activePane={activePane} number="03" title="Google BigQuery" breadcrumb={`${replay.destination.dataset}/${replay.destination.table}`} icon="bigquery" accent="google-green" tools={replay.destination.suggestedQueries.length ? <QueryList queries={replay.destination.suggestedQueries} onCopy={onCopy} /> : <MissingCapture>No destination query was captured</MissingCapture>}>
                  <EvidencePaneContent replay={replay} events={relevantEvents} />
                </TerminalPane>
              </div>
          )}
          <EdgeLane terminal={terminal} />
        </>
      ) : null}
    </PageScaffold>
  )
}
