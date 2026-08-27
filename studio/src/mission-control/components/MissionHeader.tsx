import { StatusPill } from './StatusPill';
import {
  CONNECTION_LABEL,
  CONNECTION_TONE,
  RUN_STATE_LABEL,
  RUN_STATE_TONE,
  UNAVAILABLE,
  formatDateTime,
} from './presentation';
import type { ConnectionStatus, RunState } from './types';

interface MissionHeaderProps {
  portfolioName?: string;
  runId?: string;
  runState?: RunState;
  connection: ConnectionStatus;
  updatedAt?: string;
}

export function MissionHeader({
  portfolioName,
  runId,
  runState,
  connection,
  updatedAt,
}: MissionHeaderProps) {
  return (
    <header className="mc-header">
      <div className="mc-header__identity">
        <p className="mc-header__eyebrow">Zero-Trust Migration · Mission Control</p>
        <h1 className="mc-header__title">Governed fleet migration without legacy middleware</h1>
        <p className="mc-header__promise">
          Three proprietary ERP estates move to BigQuery under one approval gate. Records are decoded and
          protected on private hardware, so raw PII never leaves the edge and no per-seat middleware licence
          sits in the path.
        </p>
      </div>

      <dl className="mc-header__facts">
        <div className="mc-fact">
          <dt>Portfolio</dt>
          <dd>{portfolioName || UNAVAILABLE}</dd>
        </div>
        <div className="mc-fact">
          <dt>Run</dt>
          <dd className="mc-mono">{runId || UNAVAILABLE}</dd>
        </div>
        <div className="mc-fact">
          <dt>Last update</dt>
          <dd>{formatDateTime(updatedAt)}</dd>
        </div>
        <div className="mc-fact">
          <dt>API authentication</dt>
          <dd>Server-side</dd>
        </div>
      </dl>

      <div className="mc-header__status">
        <StatusPill
          tone={runState ? RUN_STATE_TONE[runState] : 'neutral'}
          label={runState ? RUN_STATE_LABEL[runState] : 'No portfolio state'}
        />
        <StatusPill tone={CONNECTION_TONE[connection]} label={CONNECTION_LABEL[connection]} size="sm" />
      </div>
    </header>
  );
}
