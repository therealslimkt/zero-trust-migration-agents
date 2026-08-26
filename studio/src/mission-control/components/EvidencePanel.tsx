import { abbreviateDigest, evidenceKindLabel, eventTypeLabel, formatTimestamp } from './presentation';
import type { LaneSummary, MissionEventView } from './types';
import type { SourceId } from '../model';

export type EvidenceFilter = SourceId | 'all';

interface EvidencePanelProps {
  panelId: string;
  open: boolean;
  loading: boolean;
  events: MissionEventView[];
  summaries: LaneSummary[];
  filter: EvidenceFilter;
  onToggle: () => void;
  onFilterChange: (filter: EvidenceFilter) => void;
}

const MAX_ENTRIES = 60;

export function EvidencePanel({
  panelId,
  open,
  loading,
  events,
  summaries,
  filter,
  onToggle,
  onFilterChange,
}: EvidencePanelProps) {
  const labelFor = (sourceId?: SourceId) =>
    summaries.find((summary) => summary.sourceId === sourceId)?.presentation.shortLabel ?? 'Portfolio';

  const filtered = filter === 'all' ? events : events.filter((event) => event.sourceId === filter);
  const ordered = [...filtered].sort((a, b) => (b.timestamp ?? '').localeCompare(a.timestamp ?? ''));
  const visible = ordered.slice(0, MAX_ENTRIES);

  return (
    <section className="mc-panel mc-evidence" aria-labelledby={`${panelId}-heading`}>
      <div className="mc-panel__head">
        <h2 className="mc-section-heading" id={`${panelId}-heading`}>
          Evidence
        </h2>
        <button
          className="mc-button mc-button--quiet mc-button--sm"
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
        >
          {open ? 'Hide' : 'Show'}
          <span className="mc-sr-only"> evidence panel</span>
        </button>
      </div>

      <div className="mc-evidence__body" id={panelId} hidden={!open} tabIndex={-1}>
        <div className="mc-filters" role="group" aria-label="Filter evidence by source">
          <button
            className={`mc-filter${filter === 'all' ? ' mc-filter--active' : ''}`}
            type="button"
            aria-pressed={filter === 'all'}
            onClick={() => onFilterChange('all')}
          >
            All
          </button>
          {summaries.map((summary) => (
            <button
              className={`mc-filter${filter === summary.sourceId ? ' mc-filter--active' : ''}`}
              key={summary.sourceId}
              type="button"
              aria-pressed={filter === summary.sourceId}
              onClick={() => onFilterChange(summary.sourceId)}
            >
              {summary.presentation.shortLabel}
            </button>
          ))}
        </div>

        {loading ? <p className="mc-muted">Loading events…</p> : null}

        {!loading && visible.length === 0 ? (
          <p className="mc-muted">
            {filter === 'all'
              ? 'No events have been received on this run yet.'
              : 'No events have been received for this source yet.'}
          </p>
        ) : null}

        <ol className="mc-evidence__list">
          {visible.map((event) => (
            <li className="mc-evidence__item" key={event.eventId}>
              <div className="mc-evidence__meta">
                <time className="mc-mono" dateTime={event.timestamp}>
                  {formatTimestamp(event.timestamp)}
                </time>
                <span className="mc-evidence__scope">{labelFor(event.sourceId)}</span>
              </div>
              <p className="mc-evidence__type">{eventTypeLabel(event.eventType)}</p>
              <p className="mc-evidence__summary">{event.summary}</p>
              {event.evidenceReferences?.length ? (
                <ul className="mc-evidence__refs">
                  {event.evidenceReferences.map((reference) => (
                    <li key={`${event.eventId}-${reference.artifactId}`}>
                      <span className="mc-evidence__kind">{evidenceKindLabel(reference.kind)}</span>
                      <span className="mc-mono mc-evidence__artifact">{reference.artifactId}</span>
                      <span className="mc-mono mc-muted" title={reference.digest}>
                        {abbreviateDigest(reference.digest)}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mc-muted mc-evidence__norefs">No artifacts referenced by this event.</p>
              )}
            </li>
          ))}
        </ol>

        {ordered.length > visible.length ? (
          <p className="mc-muted">{`Showing the ${MAX_ENTRIES} most recent of ${ordered.length} events.`}</p>
        ) : null}
      </div>
    </section>
  );
}
