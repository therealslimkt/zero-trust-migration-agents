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
  const orderedEvents = useMemo(() => [...manifest.events].sort((a, b) => a.sequence - b.sequence), [manifest.events]);
  const source = manifest.sources.find((candidate) => candidate.sourceId === selectedSource) ?? manifest.sources[0];
  const activeEvent = orderedEvents[cursor];

  useEffect(() => {
    if (!playing || orderedEvents.length < 2) return;
    const timer = window.setInterval(() => {
      setCursor((current) => {
        if (current >= orderedEvents.length - 1) {
          setPlaying(false);
          return current;
        }
        return current + 1;
      });
    }, reducedMotion ? 1200 : 700);
    return () => window.clearInterval(timer);
  }, [orderedEvents.length, playing, reducedMotion]);

  if (!source) {
    return <main className="replay-empty">This published bundle contains no source replay.</main>;
  }

  const visibleActions = source.compiler.actions.filter((action) => !activeEvent || action.sequence <= activeEvent.sequence);

  return (
    <main className="replay-shell mission-control-root">
      <header className="replay-commandbar">
        <div className="replay-commandbar__identity">
          <span className="replay-kicker">IMMUTABLE SYNTHETIC RUN</span>
          <h1>{manifest.title}</h1>
          <span className="replay-mono">{manifest.sourceRunId}</span>
        </div>
        <div className="replay-commandbar__signals">
          <ReplayBadge mode="replay" detail="RECORDED RUN" size="md" />
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

      <AnimatePresence mode="wait">
        <motion.section
          key={source.sourceId}
          className="replay-three-pane"
          initial={reducedMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reducedMotion ? { opacity: 0 } : { opacity: 0, y: -5 }}
          transition={{ duration: reducedMotion ? 0 : 0.24 }}
        >
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
            {source.source.samples[0] ? <>
              <h2 className="replay-section-title">Published synthetic sample</h2>
              <div className="replay-sample">
                {source.source.samples[0].decodedFields.map((field) => <div key={field.name}><span>{field.name}</span><code>{String(field.value)}</code></div>)}
              </div>
            </> : null}
          </TerminalWindow>

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
          </TerminalWindow>
        </motion.section>
      </AnimatePresence>

      <section className="replay-transport" aria-label="Recorded replay controls">
        <button className="replay-button" disabled={cursor === 0} onClick={() => { setPlaying(false); setCursor((value) => Math.max(0, value - 1)); }} aria-label="Previous recorded event"><PixelIcon name="rewind" /></button>
        <button className="replay-button replay-button--primary" disabled={orderedEvents.length < 2} onClick={() => { if (cursor >= orderedEvents.length - 1) setCursor(0); setPlaying((value) => !value); }}>
          <PixelIcon name={playing ? "cross-pixel" : "play"} color={playing ? "google-red" : "google-green"} glow /> {playing ? "Pause replay" : "Play recorded run"}
        </button>
        <input aria-label="Recorded event position" type="range" min={0} max={Math.max(0, orderedEvents.length - 1)} value={cursor} onChange={(event) => { setPlaying(false); setCursor(Number(event.target.value)); }} />
        <div className="replay-transport__event"><span>{activeEvent ? `${activeEvent.sequence}/${orderedEvents.at(-1)?.sequence}` : "No events"}</span><strong>{activeEvent?.summary ?? "This bundle has no recorded events."}</strong><small>{activeEvent ? formatTime(activeEvent.timestamp) : ""}</small></div>
      </section>
    </main>
  );
}
