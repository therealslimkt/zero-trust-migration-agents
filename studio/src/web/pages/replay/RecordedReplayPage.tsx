import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";

import type { DemoManifest, SourceId } from "../../contracts.generated";
import { PixelIcon, ReplayBadge, StatusBeacon, TerminalWindow } from "../../shared/ui";
import "./recorded-replay.css";

export interface RecordedReplayPageProps {
  readonly manifest: DemoManifest;
  readonly onExit?: () => void;
}

const sourceOrder: readonly SourceId[] = ["jde", "maxdb", "btrieve"];
type ReplayPane = "source" | "compiler" | "destination";

function shortDigest(value: string): string {
  return value.length > 22 ? `${value.slice(0, 12)}…${value.slice(-8)}` : value;
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function RecordedReplayPage({ manifest, onExit }: RecordedReplayPageProps) {
  const reducedMotion = useReducedMotion();
  const [selectedSource, setSelectedSource] = useState<SourceId>(manifest.sources[0]?.sourceId ?? "jde");
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [practiceDecision, setPracticeDecision] = useState<"approve" | "reject">();
  const [activePane, setActivePane] = useState<ReplayPane>("source");
  const orderedEvents = useMemo(() => [...manifest.events].sort((a, b) => a.sequence - b.sequence), [manifest.events]);
  const gateIndex = orderedEvents.findIndex((event) => event.sequence === manifest.practiceApproval.pauseAfterSequence);
  const source = manifest.sources.find((candidate) => candidate.sourceId === selectedSource) ?? manifest.sources[0];
  const activeEvent = orderedEvents[cursor];

  useEffect(() => {
    if (!playing || reducedMotion || orderedEvents.length < 2) return;
    const timer = window.setInterval(() => {
      setCursor((current) => {
        if (practiceDecision === undefined && gateIndex >= 0 && current >= gateIndex) {
          setPlaying(false);
          return current;
        }
        if (current >= orderedEvents.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, 700);
    return () => window.clearInterval(timer);
  }, [gateIndex, orderedEvents.length, playing, practiceDecision, reducedMotion]);

  if (!source) {
    return <main className="replay-empty">This published bundle contains no source replay.</main>;
  }

  const visibleEventIDs = new Set(orderedEvents.slice(0, cursor + 1).map((event) => event.eventId));
  const visibleActions = source.compiler.actions.filter((action) => visibleEventIDs.has(action.eventId));
  const atPracticeGate = practiceDecision === undefined && gateIndex >= 0 && cursor === gateIndex;
  const selectCursor = (next: number) => {
    setPlaying(false);
    setCursor(practiceDecision === undefined && gateIndex >= 0 ? Math.min(next, gateIndex) : next);
  };
  const decidePractice = (decision: "approve" | "reject") => {
    setPracticeDecision(decision);
    if (!reducedMotion) setPlaying(true);
  };

  return (
    <main className="replay-shell mission-control-root">
      <a href="#replay-main" className="site-skip-link">Skip to replay panes</a>
      <header className="replay-commandbar">
        <div className="replay-commandbar__identity">
          <span className="replay-kicker">IMMUTABLE SYNTHETIC RUN</span>
          <h1>{manifest.title}</h1>
          <span className="replay-mono">{manifest.sourceRunId}</span>
        </div>
        <div className="replay-commandbar__signals">
          <ReplayBadge mode="replay" detail="RECORDED DEMO REPLAY" size="md" />
          <StatusBeacon status="active" mode="steady" label="RECONCILED" />
          {onExit ? <button className="replay-button replay-button--quiet" onClick={onExit}>Exit replay</button> : null}
        </div>
      </header>

      <section className="replay-proofbar" aria-label="Publication proof">
        <div><span>Bundle digest</span><strong title={manifest.bundleDigest}>{shortDigest(manifest.bundleDigest)}</strong></div>
        <div><span>Plan digest</span><strong title={manifest.portfolioPlanDigest}>{shortDigest(manifest.portfolioPlanDigest)}</strong></div>
        <div><span>Published</span><strong>{formatTime(manifest.publishedAt)}</strong></div>
        <div><span>Result</span><strong>{manifest.reconciliation.recordsWritten.toLocaleString()} rows / {manifest.reconciliation.recordsRejected.toLocaleString()} rejected</strong></div>
      </section>

      <nav className="replay-source-tabs" aria-label="Migration sources">
        {sourceOrder.map((sourceId, index) => {
          const item = manifest.sources.find((candidate) => candidate.sourceId === sourceId);
          if (!item) return null;
          return (
            <button
              key={sourceId}
              className={sourceId === source.sourceId ? "replay-source-tab replay-source-tab--active" : "replay-source-tab"}
              onClick={() => setSelectedSource(sourceId)}
              aria-current={sourceId === source.sourceId ? "page" : undefined}
            >
              <span className={`replay-source-tab__index replay-source-tab__index--${index + 1}`}>0{index + 1}</span>
              <span><strong>{item.displayName}</strong><small>{item.hostname}</small></span>
            </button>
          );
        })}
      </nav>

      <div className="replay-pane-tabs" role="tablist" aria-label="Replay detail panes">
        {([['source', 'Source system'], ['compiler', 'Agent compiler'], ['destination', 'BigQuery destination']] as const).map(([pane, label]) => (
          <button key={pane} type="button" role="tab" aria-selected={activePane === pane} onClick={() => setActivePane(pane)}>{label}</button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        <motion.section
          id="replay-main"
          key={source.sourceId}
          className="replay-three-pane"
          initial={reducedMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -5 }}
          transition={{ duration: reducedMotion ? 0 : 0.24 }}
        >
          <div className="replay-pane" data-pane="source" data-active={activePane === "source"} data-tablet-visible={activePane !== "destination"}>
          <TerminalWindow title="Legacy source" breadcrumb={`${source.hostname}/${source.source.databaseFamily}`} accent="google-blue" scanlines cornerBrackets>
            <div className="replay-pane-heading"><span>SOURCE PROFILE</span><strong>{source.source.databaseVersion}</strong></div>
            <dl className="replay-definition-list">
              <div><dt>Database</dt><dd>{source.source.databaseFamily}</dd></div>
              <div><dt>Application</dt><dd>{source.source.applicationLayer}</dd></div>
              <div><dt>Fields</dt><dd>{source.source.schema.length}</dd></div>
              <div><dt>Samples</dt><dd>{source.source.samples.length}</dd></div>
            </dl>
            <h2 className="replay-section-title">Decoded schema</h2>
            <div className="replay-schema">
              {source.source.schema.map((field) => <div key={field.name}><code>{field.name}</code><span>{field.dataType}{field.nullable ? " · nullable" : ""}</span></div>)}
            </div>
            {source.source.samples.length ? <>
              <h2 className="replay-section-title">Published synthetic sample</h2>
              {source.source.samples.map((sample) => <div className="replay-sample" key={sample.recordId}>
                <div><span>Record</span><code>{sample.recordId}</code></div>
                <div><span>Raw bytes / hex</span><code>{sample.rawBytesHex}</code></div>
                {sample.decodedFields.map((field) => <div key={field.name}><span>{field.name}</span><code>{String(field.value)}</code></div>)}
              </div>)}
            </> : null}
          </TerminalWindow>
          </div>

          <div className="replay-pane" data-pane="compiler" data-active={activePane === "compiler"} data-tablet-visible>
          <TerminalWindow title="Agent compiler" breadcrumb="Gemma → Gemini 3.7 Flash → Beam" accent="google-yellow" scanlines cornerBrackets>
            <div className="replay-pane-heading"><span>RECORDED ACTIONS</span><strong>{visibleActions.length}/{source.compiler.actions.length}</strong></div>
            <ol className="replay-timeline">
              {visibleActions.map((action) => (
                <li key={action.eventId}>
                  <span className="replay-timeline__node" />
                  <div><small>{action.stage} · {action.agent} · {action.tool}</small><strong>{action.summary}</strong><p>{action.result}</p></div>
                </li>
              ))}
            </ol>
            <h2 className="replay-section-title">Declarative transforms</h2>
            <div className="replay-transforms">
              {source.compiler.transforms.map((transform) => <div key={`${transform.sequence}-${transform.sourceField}`}><span>{String(transform.sequence).padStart(2, "0")}</span><code>{transform.operation}</code><strong>{transform.sourceField} → {transform.targetField}</strong></div>)}
            </div>
          </TerminalWindow>
          </div>

          <div className="replay-pane" data-pane="destination" data-active={activePane === "destination"} data-tablet-visible={activePane !== "source"}>
          <TerminalWindow title="Verified destination" breadcrumb={`${source.destination.dataset}/${source.destination.table}`} accent="google-green" scanlines cornerBrackets>
            <div className="replay-pane-heading"><span>BIGQUERY EVIDENCE</span><StatusBeacon status="active" mode="steady" label="MATCHED" size="xs" /></div>
            <dl className="replay-reconciliation">
              <div><dt>Read</dt><dd>{source.destination.reconciliation.recordsRead.toLocaleString()}</dd></div>
              <div><dt>Written</dt><dd>{source.destination.reconciliation.recordsWritten.toLocaleString()}</dd></div>
              <div><dt>Rejected</dt><dd>{source.destination.reconciliation.recordsRejected.toLocaleString()}</dd></div>
              <div><dt>Output</dt><dd>{source.destination.reconciliation.outputRows.toLocaleString()}</dd></div>
            </dl>
            <h2 className="replay-section-title">Landed rows</h2>
            <div className="replay-rows">
              {source.destination.rows.map((row) => <div key={row.recordId}><strong>{row.recordId}</strong>{row.fields.map((field) => <span key={field.name}><small>{field.name}</small><code>{String(field.value)}</code></span>)}</div>)}
            </div>
            <div className="replay-evidence-card">
              <PixelIcon name="shield-check" color="google-green" glow />
              <div><span>RECONCILIATION EVIDENCE</span><code title={source.destination.reconciliation.evidence.digest}>{shortDigest(source.destination.reconciliation.evidence.digest)}</code></div>
            </div>
            <div className="replay-evidence-list" aria-label="Destination evidence references">
              {[source.destination.dataflowEvidence, source.destination.bigQueryEvidence, ...manifest.evidence].map((reference) => (
                <div key={`${reference.kind}-${reference.artifactId}`}><span>{reference.kind}</span><code title={reference.digest}>{reference.artifactId} · {shortDigest(reference.digest)}</code></div>
              ))}
            </div>
          </TerminalWindow>
          </div>
        </motion.section>
      </AnimatePresence>

      {atPracticeGate ? <section className="replay-practice-gate" role="dialog" aria-labelledby="practice-gate-title" aria-describedby="practice-gate-prompt">
        <span>PRACTICE DECISION · LOCAL ONLY</span>
        <h2 id="practice-gate-title">Replay paused at the portfolio approval gate</h2>
        <p id="practice-gate-prompt">{manifest.practiceApproval.prompt}</p>
        <code>{manifest.practiceApproval.planDigest}</code>
        <div><button className="replay-button" type="button" onClick={() => decidePractice("reject")}>Practice reject</button><button className="replay-button replay-button--primary" type="button" onClick={() => decidePractice("approve")}>Practice approve</button></div>
      </section> : null}

      <output className="visually-hidden" aria-live="polite">Recorded demo replay event {activeEvent?.sequence ?? 0}: {activeEvent?.summary ?? "No event"}{atPracticeGate ? ". Practice decision required." : ""}</output>

      <section className="replay-transport" aria-label="Recorded replay controls">
        <button className="replay-button" disabled={cursor === 0} onClick={() => selectCursor(Math.max(0, cursor - 1))} aria-label="Previous recorded event"><PixelIcon name="rewind" /></button>
        <button className="replay-button replay-button--primary" disabled={orderedEvents.length < 2 || atPracticeGate} onClick={() => {
          if (reducedMotion) selectCursor(Math.min(orderedEvents.length - 1, cursor + 1));
          else { if (cursor >= orderedEvents.length - 1) setCursor(0); setPlaying((value) => !value); }
        }}>
          <PixelIcon name={playing ? "cross-pixel" : "play"} color={playing ? "google-red" : "google-green"} glow /> {reducedMotion ? "Step forward" : playing ? "Pause replay" : "Play recorded run"}
        </button>
        <input aria-label="Recorded event position" type="range" min={0} max={Math.max(0, orderedEvents.length - 1)} value={cursor} onChange={(event) => selectCursor(Number(event.target.value))} />
        <div className="replay-transport__event"><span>{activeEvent ? `${activeEvent.sequence}/${orderedEvents.at(-1)?.sequence}` : "No events"}</span><strong>{activeEvent?.summary ?? "This bundle has no recorded events."}</strong><small>{activeEvent ? formatTime(activeEvent.timestamp) : ""}</small></div>
      </section>
    </main>
  );
}
