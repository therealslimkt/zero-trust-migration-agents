import { SkinButton, SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import { useEvents } from "../../shared/api/queries.js";
import { useUiStore } from "../../shared/model/uiStore.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const tone = (type: string): SkinStatusTone => type.includes("failed") || type.includes("denied") || type.includes("violation") ? "danger" : type.includes("approval") || type.includes("review") ? "warning" : type.includes("complete") || type.includes("grant") ? "success" : "info";

export function LiveEventStream() {
  const query = useEvents();
  const paused = useUiStore((state) => state.streamPaused);
  const toggle = useUiStore((state) => state.toggleStream);
  return (
    <SkinPanel title="A2A communications" description="One chronological contract across terminal and Studio" className="skin-widget skin-widget--wide" action={<SkinButton size="sm" variant="secondary" onPress={toggle}>{paused ? "Resume" : "Pause"}</SkinButton>}>
      <QueryState pending={query.isPending} error={query.error} empty={query.data?.length === 0} emptyMessage="Waiting for the first orchestration event.">
        <ol className="skin-event-list">
          {query.data?.slice().reverse().map((event) => (
            <li key={event.eventId}>
              <time>{formatTimestamp(event.timestamp)}</time>
              <div>
                <SkinStatus label={humanize(event.type)} tone={tone(event.type)} />
                <p>{event.summary}</p>
                <small>{event.from} → {event.to} · {event.taskId}</small>
              </div>
            </li>
          ))}
        </ol>
      </QueryState>
    </SkinPanel>
  );
}

