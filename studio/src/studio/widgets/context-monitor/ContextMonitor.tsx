import { SkinPanel, SkinStatus } from "../../../design-system/index.js";
import { useEvents } from "../../shared/api/queries.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const contextTypes = new Set(["context.intent", "context.request", "context.grant", "context.denied", "policy.violation"]);

export function ContextMonitor() {
  const query = useEvents();
  const events = query.data?.filter((event) => contextTypes.has(event.type)) ?? [];
  return (
    <SkinPanel title="Context monitor" description="Every intent, request, grant, and denial" className="skin-widget">
      <QueryState pending={query.isPending} error={query.error} empty={events.length === 0} emptyMessage="No context decisions have been recorded.">
        <div className="skin-row-list">
          {events.slice().reverse().map((event) => (
            <article className="skin-data-row" key={event.eventId}>
              <div><strong>{event.from}</strong><p>{event.summary}</p></div>
              <div className="skin-data-row__end"><SkinStatus label={humanize(event.type)} tone={event.type === "context.denied" || event.type === "policy.violation" ? "danger" : event.type === "context.grant" ? "success" : "info"} /><small>{formatTimestamp(event.timestamp)}</small></div>
            </article>
          ))}
        </div>
      </QueryState>
    </SkinPanel>
  );
}

