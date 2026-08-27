import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './App.css';

import {
  MIGRATION_SCHEMA_VERSION,
  SOURCE_ORDER,
  MissionControlModelError,
  buildMissionControlView,
  canApprove,
} from './mission-control/model';
import { MissionControlClient, MissionControlClientError } from './mission-control/client';
import { ApprovalGate } from './mission-control/components/ApprovalGate';
import { EvidencePanel } from './mission-control/components/EvidencePanel';
import { MissionHeader } from './mission-control/components/MissionHeader';
import { SourceLane } from './mission-control/components/SourceLane';
import { TrustRail } from './mission-control/components/TrustRail';
import {
  CONNECTION_LABEL,
  RUN_STATE_LABEL,
  laneEvidence,
  presentationFor,
  selectConnectionStatus,
  selectLanes,
  selectPortfolioDigest,
} from './mission-control/components/presentation';
import type { DecisionSubmission } from './mission-control/components/ApprovalGate';
import type { EvidenceFilter } from './mission-control/components/EvidencePanel';
import type {
  ConnectionStatus,
  LaneSummary,
  MissionControlSnapshot,
  MissionControlView,
  PortfolioDecisionInput,
} from './mission-control/components/types';
import type { SourceId } from './mission-control/model';

const EVIDENCE_PANEL_ID = 'mc-evidence-panel';

interface AppConfig {
  baseUrl: string;
  runId: string;
  approver: string;
  missing: string[];
}

function env(): Record<string, string | undefined> {
  return import.meta.env as unknown as Record<string, string | undefined>;
}

function readConfig(): AppConfig {
  const source = env();
  const queryRunId = new URLSearchParams(globalThis.location.search).get('runId')?.trim() ?? '';
  const runId = queryRunId || (source.VITE_MISSION_RUN_ID ?? '').trim();
  const missing: string[] = [];
  if (!runId) missing.push('VITE_MISSION_RUN_ID');
  return {
    // Same-origin is mandatory. The loopback Vite BFF injects the upstream
    // bearer token server-side; no API credential is compiled into JavaScript.
    baseUrl: '',
    runId,
    approver: (source.VITE_MISSION_APPROVER ?? '').trim(),
    missing,
  };
}

function describeError(error: unknown): string {
  if (error instanceof MissionControlClientError || error instanceof MissionControlModelError) {
    return error.message;
  }
  return 'Mission Control could not complete the operation.';
}

export default function App() {
  const config = useMemo(() => readConfig(), []);
  const configured = config.missing.length === 0;

  const [snapshot, setSnapshot] = useState<MissionControlSnapshot | null>(null);
  const [clientError, setClientError] = useState<string | null>(null);
  const [submission, setSubmission] = useState<DecisionSubmission>({ status: 'idle' });
  const [evidenceOpen, setEvidenceOpen] = useState(true);
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>('all');
  const clientRef = useRef<MissionControlClient | null>(null);

  useEffect(() => {
    if (!configured) return;

    const client = new MissionControlClient({
      baseUrl: config.baseUrl,
    });

    clientRef.current = client;
    const abort = new AbortController();
    let active = true;
    let connectionState: MissionControlSnapshot['connectionState'] = 'connecting';

    const setConnectionState = (next: MissionControlSnapshot['connectionState']) => {
      connectionState = next;
      if (!active) return;
      setSnapshot((current) => (current ? { ...current, connectionState: next } : current));
    };

    void (async () => {
      try {
        const initialRun = await client.getMigration(config.runId);
        if (!active) return;
        setClientError(null);
        setSnapshot({ run: initialRun, events: [], connectionState });

        for await (const event of client.streamEvents(config.runId, {
          signal: abort.signal,
          onConnectionStateChange: setConnectionState,
        })) {
          if (!active) return;
          setSnapshot((current) => {
            if (!current || current.events.some((candidate) => candidate.eventId === event.eventId)) return current;
            return { ...current, events: [...current.events, event] };
          });

          // Events intentionally contain no counters. Refresh the closed run
          // document after each persisted event so lane counts remain factual.
          const refreshedRun = await client.getMigration(config.runId);
          if (!active) return;
          setSnapshot((current) =>
            current ? { ...current, run: refreshedRun } : { run: refreshedRun, events: [event], connectionState },
          );
        }
      } catch (error) {
        if (!abort.signal.aborted && active) setClientError(describeError(error));
      }
    })();

    return () => {
      active = false;
      abort.abort();
      client.close();
      clientRef.current = null;
    };
  }, [configured, config.baseUrl, config.runId]);

  const composed = useMemo(() => {
    if (!snapshot) return { view: null, error: null as string | null };
    try {
      const view = buildMissionControlView(
        snapshot.run,
        snapshot.events,
        snapshot.connectionState,
      );
      return { view, error: null as string | null };
    } catch (error) {
      return { view: null, error: describeError(error) };
    }
  }, [snapshot]);

  const domainView = composed.view;
  const view: MissionControlView | null = domainView;

  // Approval eligibility is the domain layer's decision. A throwing predicate
  // fails closed rather than opening the gate.
  const approvalAllowed = useMemo(() => {
    if (!domainView) return false;
    try {
      return Boolean(canApprove(domainView));
    } catch {
      return false;
    }
  }, [domainView]);

  const lanes = useMemo(() => selectLanes(view), [view]);
  const events = useMemo(() => snapshot?.events ?? [], [snapshot?.events]);
  const summaries = useMemo<LaneSummary[]>(
    () =>
      SOURCE_ORDER.map((sourceId: SourceId) => {
        const lane = lanes.get(sourceId);
        return {
          sourceId,
          presentation: presentationFor(sourceId),
          lane,
          evidence: laneEvidence(lane, events),
        };
      }),
    [lanes, events],
  );

  const digest = selectPortfolioDigest(view);
  const loading = configured && !snapshot && !clientError;
  const fallbackConnection: ConnectionStatus = !configured
    ? 'unconfigured'
    : clientError
      ? 'failed'
      : snapshot
        ? 'live'
        : 'connecting';
  const connection = selectConnectionStatus(view, fallbackConnection);
  const streamDegraded = connection === 'stale' || connection === 'disconnected' || connection === 'failed';
  const noRunData = Boolean(snapshot) && !view?.runId && lanes.size === 0;

  const currentSubmission =
    submission.digest === undefined || submission.digest === digest ? submission : ({ status: 'idle' } as const);

  const blockedReasons = useMemo(() => {
    if (approvalAllowed) return [];
    const reasons: string[] = [];
    if (!configured) {
      reasons.push('Mission Control is not configured, so no decision can be sent.');
    } else if (!snapshot) {
      reasons.push('No portfolio snapshot has been received yet.');
    }
    if (streamDegraded) {
      reasons.push(`Event stream is ${CONNECTION_LABEL[connection].toLowerCase()}; the shown digest may be stale.`);
    }
    if (!digest) {
      reasons.push('The portfolio plan digest has not been published.');
    }
    for (const summary of summaries) {
      const label = summary.presentation.shortLabel;
      const lane = summary.lane;
      if (!lane) {
        reasons.push(`${label}: no lane data reported.`);
      } else if (lane.state === 'failed' || lane.state === 'cancelled') {
        reasons.push(
          `${label}: ${RUN_STATE_LABEL[lane.state].toLowerCase()}${lane.failureCode ? ` (${lane.failureCode})` : ''}.`,
        );
      } else if (!lane.planDigest) {
        reasons.push(`${label}: no validated plan digest.`);
      }
    }
    if (reasons.length === 0 && view?.state && view.state !== 'awaiting_approval') {
      reasons.push(`Portfolio is ${RUN_STATE_LABEL[view.state].toLowerCase()}, not awaiting approval.`);
    }
    if (reasons.length === 0) {
      reasons.push('The control plane has not opened the approval gate for this digest.');
    }
    return reasons;
  }, [approvalAllowed, configured, snapshot, streamDegraded, connection, digest, summaries, view]);

  const handleDecision = useCallback(
    (input: Omit<PortfolioDecisionInput, 'planDigest'>) => {
      const client = clientRef.current;
      if (!client || !digest) {
        setSubmission({
          status: 'error',
          decision: input.decision,
          message: 'No connected control plane or published digest.',
        });
        return;
      }
      setSubmission({ status: 'submitting', decision: input.decision, digest });
      void client
        .approveMigration(config.runId, {
          schemaVersion: MIGRATION_SCHEMA_VERSION,
          planDigest: digest,
          decision: input.decision,
          decidedBy: input.decidedBy,
          ...(input.reason === undefined ? {} : { reason: input.reason }),
        })
        .then(async () => {
          const refreshedRun = await client.getMigration(config.runId);
          setSnapshot((current) =>
            current ? { ...current, run: refreshedRun } : current,
          );
          setSubmission({ status: 'submitted', decision: input.decision, digest });
        })
        .catch((error: unknown) =>
          setSubmission({
            status: 'error',
            decision: input.decision,
            digest,
            message: describeError(error),
          }),
        );
    },
    [config.runId, digest],
  );

  const handleOpenEvidence = useCallback((sourceId: SourceId) => {
    setEvidenceFilter(sourceId);
    setEvidenceOpen(true);
    requestAnimationFrame(() => document.getElementById(EVIDENCE_PANEL_ID)?.focus());
  }, []);

  const announcement = `Portfolio ${view?.state ? RUN_STATE_LABEL[view.state] : 'state unavailable'}. Event stream ${CONNECTION_LABEL[connection]}. ${events.length} events received.`;

  return (
    <div className="mc-app">
      <a className="mc-skip" href="#mc-lanes">
        Skip to migration lanes
      </a>

      <MissionHeader
        portfolioName={view?.portfolioName}
        runId={view?.runId || config.runId}
        runState={view?.state}
        connection={connection}
        updatedAt={view?.updatedAt}
      />

      {!configured ? (
        <div className="mc-notice mc-notice--critical" role="alert">
          <h2 className="mc-notice__title">Configuration required</h2>
          <p>
            Mission Control needs a run ID. Set the following Vite environment variable, or open the page with a
            valid <span className="mc-mono">?runId=mig_…</span> query parameter, and reload:
          </p>
          <ul className="mc-notice__list">
            {config.missing.map((name) => (
              <li className="mc-mono" key={name}>
                {name}
              </li>
            ))}
          </ul>
          <p className="mc-notice__foot">
            API authentication is held by the loopback server and is never compiled into, displayed by, or logged
            from the browser application. No request is attempted while configuration is incomplete.
          </p>
        </div>
      ) : null}

      {clientError ? (
        <div className="mc-notice mc-notice--critical" role="alert">
          <h2 className="mc-notice__title">Control-plane connection failed</h2>
          <p>{clientError}</p>
        </div>
      ) : null}

      {composed.error ? (
        <div className="mc-notice mc-notice--critical" role="alert">
          <h2 className="mc-notice__title">Portfolio data could not be read</h2>
          <p>{composed.error}</p>
        </div>
      ) : null}

      {loading ? (
        <div className="mc-notice" role="status">
          <h2 className="mc-notice__title">Connecting to the control plane</h2>
          <p>
            Waiting for the first portfolio snapshot on run <span className="mc-mono">{config.runId}</span>. Lanes
            stay empty until real events arrive.
          </p>
        </div>
      ) : null}

      {streamDegraded && !clientError ? (
        <div className="mc-notice mc-notice--attention" role="status">
          <h2 className="mc-notice__title">{CONNECTION_LABEL[connection]}</h2>
          <p>
            Lane values below are the last state received from the control plane and may be out of date. Approval
            stays closed while the stream is not healthy.
          </p>
        </div>
      ) : null}

      {noRunData && !composed.error ? (
        <div className="mc-notice" role="status">
          <h2 className="mc-notice__title">No portfolio run data</h2>
          <p>
            The control plane returned no run for <span className="mc-mono">{config.runId}</span>. Nothing is
            inferred while the run is empty.
          </p>
        </div>
      ) : null}

      <TrustRail summaries={summaries} runState={view?.state} connection={connection} />

      <main className="mc-main">
        <section className="mc-lanes-section" aria-labelledby="mc-lanes-heading">
          <div className="mc-section-head">
            <h2 className="mc-section-heading" id="mc-lanes-heading">
              Migration lanes
            </h2>
            <p className="mc-section-note">
              All three estates migrate together under one gate. States and counters come from the durable
              control-plane snapshot; evidence and activity come from its persisted event log.
            </p>
          </div>
          <ol className="mc-lanes" id="mc-lanes" tabIndex={-1}>
            {summaries.map((summary) => (
              <SourceLane
                evidencePanelId={EVIDENCE_PANEL_ID}
                key={summary.sourceId}
                loading={loading}
                onOpenEvidence={handleOpenEvidence}
                summary={summary}
              />
            ))}
          </ol>
        </section>

        <aside className="mc-aside" aria-label="Approval and evidence">
          <ApprovalGate
            key={digest ?? 'no-digest'}
            approvalAllowed={approvalAllowed}
            blockedReasons={blockedReasons}
            defaultApprover={config.approver}
            digest={digest}
            onSubmit={handleDecision}
            runState={view?.state}
            submission={currentSubmission}
          />
          <EvidencePanel
            events={events}
            filter={evidenceFilter}
            loading={loading}
            onFilterChange={setEvidenceFilter}
            onToggle={() => setEvidenceOpen((open) => !open)}
            open={evidenceOpen}
            panelId={EVIDENCE_PANEL_ID}
            summaries={summaries}
          />
        </aside>
      </main>

      <p aria-live="polite" className="mc-sr-only">
        {announcement}
      </p>
    </div>
  );
}
