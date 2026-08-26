import { StatusPill } from './StatusPill';
import {
  LANE_STAGES,
  RUN_STATE_LABEL,
  RUN_STATE_TONE,
  UNAVAILABLE,
  abbreviateDigest,
  distinctKinds,
  evidenceKindLabel,
  formatCount,
  humaniseCode,
  stageStatuses,
} from './presentation';
import type { StageStatus } from './presentation';
import type { LaneSummary } from './types';

interface SourceLaneProps {
  summary: LaneSummary;
  loading: boolean;
  evidencePanelId: string;
  onOpenEvidence: (sourceId: LaneSummary['sourceId']) => void;
}

const STAGE_STATUS_TEXT: Record<StageStatus, string> = {
  done: 'complete',
  current: 'in progress',
  pending: 'not started',
  halted: 'halted',
};

export function SourceLane({ summary, loading, evidencePanelId, onOpenEvidence }: SourceLaneProps) {
  const { presentation, lane, evidence } = summary;
  const headingId = `mc-lane-${summary.sourceId}`;
  const state = lane?.state;
  const statuses = stageStatuses(state);
  const kinds = distinctKinds(evidence);
  const hostname = lane?.hostname || presentation.hostname;
  const tone = state ? RUN_STATE_TONE[state] : 'neutral';

  return (
    <li className={`mc-lane mc-lane--${tone}`}>
      <article aria-labelledby={headingId} aria-busy={loading || undefined}>
        <div className="mc-lane__head">
          <div className="mc-lane__identity">
            <h3 className="mc-lane__title" id={headingId}>
              {presentation.label}
            </h3>
            <p className="mc-lane__meta">
              <span className="mc-mono">{hostname || 'hostname unavailable'}</span>
              <span className="mc-dot-sep" aria-hidden="true" />
              <span>{presentation.legacyFormat || 'legacy format unavailable'}</span>
            </p>
          </div>
          <StatusPill
            tone={tone}
            label={state ? RUN_STATE_LABEL[state] : loading ? 'Loading' : 'No data reported'}
          />
        </div>

        <div className="mc-lane__body">
          <div className="mc-lane__block mc-lane__block--stages">
            <h4 className="mc-block-heading">Progress</h4>
            <ol className="mc-stages">
              {LANE_STAGES.map((stage, index) => (
                <li
                  className={`mc-stage mc-stage--${statuses[index]}`}
                  key={stage.id}
                  aria-current={statuses[index] === 'current' ? 'step' : undefined}
                >
                  <span className="mc-stage__dot" aria-hidden="true" />
                  <span className="mc-stage__label">{stage.label}</span>
                  <span className="mc-sr-only">{` ${STAGE_STATUS_TEXT[statuses[index]]}`}</span>
                </li>
              ))}
            </ol>
          </div>

          <div className="mc-lane__block">
            <h4 className="mc-block-heading">Records</h4>
            <dl className="mc-metrics">
              <div className="mc-metric">
                <dt>Read</dt>
                <dd>{formatCount(lane?.recordsRead)}</dd>
              </div>
              <div className="mc-metric">
                <dt>Written</dt>
                <dd>{formatCount(lane?.recordsWritten)}</dd>
              </div>
              <div className={`mc-metric${lane?.recordsRejected ? ' mc-metric--flagged' : ''}`}>
                <dt>Rejected</dt>
                <dd>{formatCount(lane?.recordsRejected)}</dd>
              </div>
            </dl>
          </div>

          <div className="mc-lane__block">
            <h4 className="mc-block-heading">Plan &amp; evidence</h4>
            <p className="mc-lane__digest">
              {lane?.planDigest ? (
                <span className="mc-mono" title={lane.planDigest}>
                  {abbreviateDigest(lane.planDigest)}
                </span>
              ) : (
                <span className="mc-muted">Plan digest not published</span>
              )}
            </p>
            {kinds.length > 0 ? (
              <ul className="mc-chips">
                {kinds.map((kind) => (
                  <li className="mc-chip" key={kind}>
                    {evidenceKindLabel(kind)}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mc-muted">No evidence references received</p>
            )}
            <button
              className="mc-link-button"
              type="button"
              aria-controls={evidencePanelId}
              onClick={() => onOpenEvidence(summary.sourceId)}
            >
              {`Open evidence (${evidence.length})`}
              <span className="mc-sr-only">{` for ${presentation.label}`}</span>
            </button>
          </div>

          <div className="mc-lane__block">
            <h4 className="mc-block-heading">BigQuery target</h4>
            <p className="mc-lane__target">
              {presentation.bigQueryTarget ? (
                <span className="mc-mono">{presentation.bigQueryTarget}</span>
              ) : (
                <span className="mc-muted">Target not published</span>
              )}
            </p>
            <p className="mc-lane__target-note">
              {evidence.some((reference) => reference.kind === 'bigquery_table')
                ? 'Table write evidenced by the control plane'
                : 'No verified write yet'}
            </p>
          </div>
        </div>

        {lane?.failureCode ? (
          <p className="mc-lane__failure">
            <span className="mc-lane__failure-label">Failure</span>
            <span>{humaniseCode(lane.failureCode)}</span>
            <span className="mc-mono mc-muted">{lane.failureCode}</span>
          </p>
        ) : null}

        {!lane && !loading ? (
          <p className="mc-lane__empty">
            This source has not reported yet. Nothing is inferred for it: counts, digest, and evidence stay{' '}
            {UNAVAILABLE} until the control plane sends an event.
          </p>
        ) : null}
      </article>
    </li>
  );
}
