import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { LiveWebClient } from '../../client'
import { WEB_SCHEMA_VERSION, type LiveRunSummary, type SourceId } from '../../contracts.generated'
import { useTerminalFrameStream, TerminalFrameRenderer } from '../../features/terminal'
import { StageColumn } from './StageColumn'
import { QuarantinePanel } from './QuarantinePanel'
import { TerminalBusy } from './TerminalBusy'
import { TerminalPrompt } from './TerminalPrompt'
import { usePacedFeed } from './usePacedFeed'
import { stages, type CompileResult, type EmbedResult, type LandResult, type StageCartridge } from './stageClient'
import { useAuth } from '../../features/auth'
import { PixelIcon, TerminalWindow } from '../../shared/ui'
import '../public/public-pages.css'

type TranslationIssue = {
  /** Placeholder shape for a research-agent handoff; hand-authored for now. */
  readonly code: string
  readonly title: string
  readonly detail: string
}

type Cartridge = {
  readonly id: SourceId
  readonly label: string
  readonly host: string
  readonly defect: string
  readonly driver: string
  readonly driverNote: string
  readonly jar: string
  readonly jarNote: string
  readonly issues: readonly TranslationIssue[]
}

const CARTRIDGES: readonly Cartridge[] = [
  { id: 'jde', label: 'JD Edwards EnterpriseOne 9.2 / IBM i', host: 'legacy-jde-db',
    defect: 'EBCDIC cp037 text and COMP-3 packed decimal',
    driver: 'IBM Db2 for i', driverNote: 'synthetic emulator speaks SQL directly',
    jar: 'jt400.jar', jarNote: 'declared for the production IBM i path; fingerprinted before use',
    issues: [
      { code: 'JDE-F0101-001', title: 'COMP-3 packed decimal',
        detail: 'ABAN8 holds digits two-per-byte with a sign nibble. Unpacked to BIGQUERY INT64; a nibble outside 0-9 or a sign outside C/D/F is refused.' },
      { code: 'JDE-F0101-002', title: 'EBCDIC cp037 text',
        detail: 'ABALPH and ABTAX are EBCDIC, not ASCII. Transcoded to BIGQUERY STRING; cp037 maps all 256 bytes so text cannot fail structurally.' },
      { code: 'JDE-F0911-003', title: 'CYYDDD julian dates',
        detail: 'UPMJ packs century, year and day-of-year into one integer. Day 366 in a non-leap year and day 0 are invalid and are quarantined, not coerced.' },
    ] },
  { id: 'maxdb', label: 'SAP ERP / MaxDB 7.9', host: 'legacy-maxdb',
    defect: 'clustered records, each separately zlib-compressed',
    driver: 'SAP MaxDB', driverNote: 'synthetic emulator speaks SQL directly',
    jar: 'sapdbc.jar', jarNote: 'declared for the production MaxDB path',
    issues: [
      { code: 'SAP-KNA1-001', title: 'zlib cluster records',
        detail: 'Each record is separately compressed inside one blob. Length and CRC32 are verified before inflation; a failed check refuses that record alone.' },
    ] },
  { id: 'btrieve', label: 'Sage 300 / Actian Zen', host: 'legacy-btrieve-db',
    defect: 'fixed-length Btrieve pages with no SQL layer',
    driver: 'Actian Zen', driverNote: 'synthetic emulator speaks SQL directly',
    jar: 'pvjdbc4.jar', jarNote: 'declared for the production Btrieve path',
    issues: [
      { code: 'SAGE-ARCUS-001', title: 'Fixed-length pages',
        detail: 'Records sit at byte offsets inside 4 KiB pages with no schema. Layout comes from the DDF dictionary; an unrecognised page layout fails closed.' },
    ] },
]

function useLiveClient(): LiveWebClient {
  const { getIdToken } = useAuth()
  // In the credential-free local demo the browser has no Identity Platform
  // session; the loopback BFF supplies the one fixed demo identity instead and
  // overwrites this header. In every hosted build the real token is required.
  return useMemo(
    () => new LiveWebClient(async () => {
      try {
        return await getIdToken()
      } catch (error) {
        if (import.meta.env.DEV) return ''
        throw error
      }
    }),
    [getIdToken],
  )
}

function StatePill({ state }: { readonly state: string }) {
  return (
    <span className={`mc-pill mc-pill--${state.replace(/[ _]/g, '-')}`}>{state}</span>
  )
}

export function MissionControlPage() {
  const client = useLiveClient()
  const cache = useQueryClient()
  const [selected, setSelected] = useState<SourceId>('jde')

  const runs = useQuery({
    queryKey: ['mc-runs'],
    queryFn: () => client.listRuns(),
    refetchInterval: 5_000,
  })
  const run: LiveRunSummary | undefined = runs.data?.runs[0]

  const live = useTerminalFrameStream(client, run?.runId, selected)
  // Marking the frame count as a stage starts is what separates this session's
  // output from the run's backlog; nothing before the mark is replayed.
  const [mark, setMark] = useState<number | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const beginStage = <T,>(work: () => Promise<T>, label: string) => {
    setMark(live.frames.length)
    setBusy(label)
    return work().finally(() => setBusy(null))
  }
  const paced = usePacedFeed(live, mark)
  const terminal = paced.feed

  const approve = useMutation({
    mutationFn: () => client.decideRun(run!.runId, {
      schemaVersion: WEB_SCHEMA_VERSION,
      planDigest: run!.portfolioPlanDigest!,
      decision: 'approve',
    }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ['mc-runs'] }),
  })

  const [catalog, setCatalog] = useState<readonly StageCartridge[]>([])
  const [loaded, setLoaded] = useState<string | null>(null)
  const [compiled, setCompiled] = useState<CompileResult | null>(null)
  const [landed, setLanded] = useState<LandResult | null>(null)
  const [embedded, setEmbedded] = useState<EmbedResult | null>(null)
  const [maximized, setMaximized] = useState<'source' | 'compiler' | 'destination' | null>(null)

  useEffect(() => { void stages.list().then(setCatalog).catch(() => setCatalog([])) }, [])
  useEffect(() => { setLoaded(null); setCompiled(null); setLanded(null); setEmbedded(null); setMark(null) }, [selected])
  useEffect(() => {
    if (!maximized) return
    const leave = (event: KeyboardEvent) => { if (event.key === 'Escape') setMaximized(null) }
    window.addEventListener('keydown', leave)
    return () => window.removeEventListener('keydown', leave)
  }, [maximized])

  const entry = catalog.find((candidate) => candidate.id === selected)
  const source = run?.sources.find((candidate) => candidate.sourceId === selected)
  const cartridge = CARTRIDGES.find((candidate) => candidate.id === selected)!
  const awaiting = run?.state === 'awaiting_approval'

  return (
    <main className={maximized ? 'mc-page mc-page--maximized' : 'mc-page'}>
      <header className="mc-head">
        <div>
          <span className="mc-eyebrow">LIVE PORTFOLIO · BACKEND-DRIVEN MIRRORS</span>
          <h1>Mission Control</h1>
          <p>
            Every frame below was admitted by the Go control plane and replayed over its event
            stream. Nothing on this page is generated in the browser.
          </p>
        </div>
        <div className="mc-status">
          {/* This page drives the stages directly, so it reports its own
              progress. The run's portfolio state belongs to the full pipeline
              and would otherwise show a stale COMPLETED from an earlier run. */}
          <StatePill state={
            landed ? 'landed' : compiled ? 'converted' : loaded ? 'sandbox ready' : 'idle'
          } />
          <span className="mc-runid">{run?.runId ?? '—'}</span>
          <span className={`mc-conn mc-conn--${terminal.connection}`}>
            stream {terminal.connection}
          </span>
        </div>
      </header>

      <section className="mc-banner" aria-label="Loaded cartridge">
        <div className="mc-banner__row">
          <label htmlFor="cartridge">Loaded cartridge</label>
          <select id="cartridge" value={selected}
                  onChange={(event) => setSelected(event.target.value as SourceId)}>
            {CARTRIDGES.map((entry) => (
              <option key={entry.id} value={entry.id}>{entry.label}</option>
            ))}
          </select>
          <span className="mc-host"><PixelIcon name="compute-engine" size="xs" color="muted" />{cartridge.host}</span>

          {/* Counts reflect what this session actually ran, not the run's backlog. */}
          <dl className="mc-tally">
            <div><dt>Read</dt><dd>{compiled?.read ?? source?.recordsRead ?? 0}</dd></div>
            <div><dt>Accepted</dt><dd>{compiled?.records ?? source?.recordsWritten ?? 0}</dd></div>
            <div className={(compiled?.rejected ?? 0) > 0 ? 'mc-tally--bad' : undefined}>
              <dt>Quarantined</dt><dd>{compiled?.rejected ?? source?.recordsRejected ?? 0}</dd>
            </div>
            <div className={landed?.matched ? 'mc-tally--good' : undefined}>
              <dt>Written</dt><dd>{landed?.rowsWritten ?? 0}</dd>
            </div>
          </dl>
        </div>

        <div className="mc-issues">
          <span className="mc-issues__label">
            <PixelIcon name="alert-triangle" size="xs" color="google-yellow" />
            {cartridge.issues.length} translation issues identified
          </span>
          {cartridge.issues.map((issue) => (
            <article key={issue.code} className="mc-issue">
              <header><code>{issue.code}</code><h3>{issue.title}</h3></header>
              <p>{issue.detail}</p>
            </article>
          ))}
        </div>
      </section>

      {awaiting && run?.portfolioPlanDigest ? (
        <section className="mc-approval" aria-label="Approval gate">
          <div>
            <h2>One decision binds this run</h2>
            <p>
              Approving commits the exact portfolio digest below. The backend takes the approver
              from the verified identity; a stale digest is refused.
            </p>
            <code>{run.portfolioPlanDigest}</code>
          </div>
          <button type="button" className="mc-approve" disabled={approve.isPending}
                  onClick={() => approve.mutate()}>
            {approve.isPending ? 'Approving…' : 'Approve this digest'}
          </button>
        </section>
      ) : null}

      {maximized ? (
        <button type="button" className="mc-restore" onClick={() => setMaximized(null)}>
          ✕  Restore all three mirrors
        </button>
      ) : null}

      <div className="mc-lanes">
        <StageColumn
          step="01" lane="source" maximizedLane={maximized} accent="blue" icon="compute-engine"
          title="Sandbox Database Image"
          subtitle={`A byte-for-byte image of ${cartridge.driver}, sealed on its own network.`}
          stackLabel="Sandbox"
          stackNote={`A Compute Engine host runs the ${cartridge.driver} image under Docker and gVisor, so the migration reads a faithful copy of the source without ever touching production.`}
          chips={[
            { icon: 'compute-engine', label: 'Compute Engine', tone: 'blue' },
            { icon: 'docker', label: 'Docker', tone: 'blue' },
            { icon: 'lock', label: 'gVisor', tone: 'green' },
            { icon: 'db2', label: cartridge.driver, tone: 'blue' },
          ]}
          runLabel="Load cartridge onto the VM"
          done={Boolean(loaded)}
          doneLabel="Cartridge loaded"
          ready
          onRun={() => beginStage(async () => { setLoaded((await stages.load(selected)).service) }, 'bringing the sealed cartridge online')}
          queries={loaded ? entry?.queries : undefined}
        >
          <TerminalWindow title="Source mirror" breadcrumb={`${selected}/source`}
                          accent="google-blue" variant="glass" scanlines
                          minHeight={maximized === 'source' ? '62vh' : '260px'}
                          maxHeight={maximized === 'source' ? '72vh' : '40vh'}
                          isMaximized={maximized === 'source'}
                          onMaximize={(next) => setMaximized(next ? 'source' : null)}
                          footer={<><span>{paced.playing
                                     ? `REPLAYING ADMITTED FRAMES ${paced.shown}/${paced.total}`
                                     : 'BACKEND-ADMITTED FRAMES ONLY'}</span>
                                   <span>{paced.playing
                                     ? <button type="button" className="mirror-skip"
                                               onClick={paced.skip}>skip</button>
                                     : (terminal.cursor ?? 'NO CURSOR')}</span></>}>
            {busy && terminal.frames.filter((f) => f.lane === 'source').length === 0
              ? <TerminalBusy label={busy} />
              : <TerminalFrameRenderer feed={terminal} lane="source" label="Legacy source" />}
            <TerminalPrompt
              placeholder={`SELECT … FROM f0911`}
              disabled={!loaded}
              hint="load the cartridge first"
              onSubmit={(sql) => beginStage(() => stages.source(selected, sql), 'querying the source')}
            />
          </TerminalWindow>
        </StageColumn>

        <StageColumn
          step="02" lane="compiler" maximizedLane={maximized} accent="yellow" icon="apache-beam"
          title="Agentic BigQuery Migration"
          subtitle={`PRISMA plans the translation on gemini-3.5-flash; VALE certifies it. Neither emits code — ${cartridge.jar} and the Beam DoFn do the work.`}
          stackLabel="Migration agent"
          stackNote={`${cartridge.jar} is declared and fingerprinted for the production path; Apache Beam runs the code-owned decoder, and Gemini only chooses rename, cast and drop.`}
          chips={[
            { icon: 'jdbc-jar', label: cartridge.jar, tone: 'gold' },
            { icon: 'apache-beam', label: 'Apache Beam 2.75.0', tone: 'green' },
            { icon: 'gemini', label: 'gemini-3.5-flash', tone: 'blue' },
          ]}
          runLabel="Run the conversion"
          done={Boolean(compiled)}
          doneLabel="Conversion complete"
          ready={Boolean(loaded)}
          blockedReason="Load the cartridge first."
          onRun={() => beginStage(async () => { setCompiled(await stages.compile(selected)) }, 'running the Beam pipeline')}
        >
          {compiled ? (
            <>
              <dl className="stage__facts">
                <div><dt>Read</dt><dd>{compiled.read}</dd></div>
                <div><dt>Accepted</dt><dd>{compiled.records}</dd></div>
                <div><dt>Quarantined</dt><dd>{compiled.rejected}</dd></div>
                <div><dt>Beam</dt><dd>{compiled.beamVersion}</dd></div>
                <div><dt>Target table</dt><dd>{compiled.table}</dd></div>
                {compiled.mapping.map((row) => (
                  <div key={row.column}><dt>{row.column}</dt><dd>{row.dataClass}</dd></div>
                ))}
              </dl>
              <QuarantinePanel cartridge={selected} rows={compiled.quarantine} read={compiled.read} />
            </>
          ) : null}
          <TerminalWindow title="Compiler mirror" breadcrumb={`${selected}/compiler`}
                          accent="google-yellow" variant="glass" scanlines
                          minHeight={maximized === 'compiler' ? '62vh' : '260px'}
                          maxHeight={maximized === 'compiler' ? '72vh' : '40vh'}
                          isMaximized={maximized === 'compiler'}
                          onMaximize={(next) => setMaximized(next ? 'compiler' : null)}
                          footer={<><span>{paced.playing
                                     ? `REPLAYING ADMITTED FRAMES ${paced.shown}/${paced.total}`
                                     : 'BACKEND-ADMITTED FRAMES ONLY'}</span>
                                   <span>{paced.playing
                                     ? <button type="button" className="mirror-skip"
                                               onClick={paced.skip}>skip</button>
                                     : (terminal.cursor ?? 'NO CURSOR')}</span></>}>
            {busy && terminal.frames.filter((f) => f.lane === 'compiler').length === 0
              ? <TerminalBusy label={busy} />
              : <TerminalFrameRenderer feed={terminal} lane="compiler" label="Agent compiler" />}
          </TerminalWindow>
        </StageColumn>

        <StageColumn
          step="03" lane="destination" maximizedLane={maximized} accent="green" icon="bigquery"
          title="BigQuery"
          subtitle="Typed columns land under an explicit schema, the counts reconcile, and the rows are embedded in place so the table is AI-ready."
          stackLabel="Warehouse"
          stackNote="Rows land under a declared schema, reconcile against the source counts, and are embedded in BigQuery itself so the data is queryable by meaning, not just by column."
          chips={[
            { icon: 'bigquery', label: 'BigQuery', tone: 'green' },
            { icon: 'shield-check', label: 'Explicit schema', tone: 'green' },
            { icon: 'gemini', label: 'Embeddings', tone: 'blue' },
            { icon: 'check-pixel', label: 'Reconciled', tone: 'green' },
          ]}
          runLabel="Land it in BigQuery"
          done={Boolean(landed)}
          doneLabel="Landed in BigQuery"
          ready={Boolean(compiled)}
          blockedReason="Run the conversion first."
          onRun={() => beginStage(async () => { setLanded(await stages.land(selected)) }, 'loading BigQuery')}
          extra={landed ? {
            label: 'Embed for AI',
            done: Boolean(embedded),
            doneLabel: 'Embedded in BigQuery',
            run: () => beginStage(async () => { setEmbedded(await stages.embed(selected)) },
                                  'embedding in BigQuery'),
          } : undefined}
          queries={landed?.queries.map((sql, index) => ({
            title: index === 0 ? 'Read the landed rows' : 'Count the landed rows', sql }))}
        >
          {embedded ? (
            <dl className="stage__facts">
              <div><dt>Embedded</dt><dd>{embedded.rows} rows</dd></div>
              <div><dt>Dimensions</dt><dd>{embedded.dimensions}</dd></div>
              <div><dt>Vector table</dt><dd>{embedded.table.split('.').pop()}</dd></div>
            </dl>
          ) : null}
          {landed ? (
            <dl className="stage__facts">
              <div><dt>Table</dt><dd>{landed.table}</dd></div>
              <div><dt>Load job</dt><dd>{landed.jobId}</dd></div>
              <div><dt>Reconciliation</dt>
                <dd className={landed.matched ? 'stage__ok' : 'stage__bad'}>
                  read {landed.rowsRead} = written {landed.rowsWritten}
                  {landed.matched ? ' · MATCHED' : ' · MISMATCHED'}
                </dd></div>
            </dl>
          ) : null}
          <TerminalWindow title="Destination mirror" breadcrumb={`${selected}/destination`}
                          accent="google-green" variant="glass" scanlines
                          minHeight={maximized === 'destination' ? '62vh' : '260px'}
                          maxHeight={maximized === 'destination' ? '72vh' : '40vh'}
                          isMaximized={maximized === 'destination'}
                          onMaximize={(next) => setMaximized(next ? 'destination' : null)}
                          footer={<><span>{paced.playing
                                     ? `REPLAYING ADMITTED FRAMES ${paced.shown}/${paced.total}`
                                     : 'BACKEND-ADMITTED FRAMES ONLY'}</span>
                                   <span>{paced.playing
                                     ? <button type="button" className="mirror-skip"
                                               onClick={paced.skip}>skip</button>
                                     : (terminal.cursor ?? 'NO CURSOR')}</span></>}>
            {busy && terminal.frames.filter((f) => f.lane === 'destination').length === 0
              ? <TerminalBusy label={busy} />
              : <TerminalFrameRenderer feed={terminal} lane="destination" label="Verified destination" />}
            <TerminalPrompt
              placeholder={embedded
                ? 'Ask in plain language, or paste a SELECT'
                : 'SELECT … FROM `project.dataset.table`'}
              disabled={!landed}
              hint="land the rows first"
              onSubmit={(text) => beginStage(
                () => (embedded && !/^\s*select\s/i.test(text)
                  ? stages.search(selected, text)
                  : stages.bq(selected, text)),
                embedded && !/^\s*select\s/i.test(text) ? 'searching by meaning' : 'querying BigQuery')}
            />
          </TerminalWindow>
        </StageColumn>
      </div>

      <p className="mc-foot">
        Frames are produced by <code>scripts/mission_control_pipeline.py</code>, admitted over the
        loopback-only producer endpoint, and persisted before the browser ever sees them. Source
        bytes, credentials and connection strings never appear in a frame.
      </p>
    </main>
  )
}
