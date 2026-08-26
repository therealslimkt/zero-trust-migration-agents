import { SkinPanel, SkinStatus } from "../../../design-system/index.js";
import { useEvents } from "../../shared/api/queries.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

export function A2AMailroom() {
  const query = useEvents();
  const latest = query.data?.at(-1);

  return (
    <SkinPanel title="Dispatch desk" description="The newest envelope moving through the agent network" className="skin-widget skin-widget--wide skin-mailroom-panel">
      <QueryState pending={query.isPending} error={query.error} empty={!latest} emptyMessage="The mailroom is quiet. The next agent signal will appear here.">
        {latest ? (
          <div className="skin-mailroom">
            <section className="skin-mailroom__address" aria-label="Dispatch sender">
              <span>From</span>
              <strong>{humanize(latest.from)}</strong>
              <small>{latest.from}</small>
            </section>
            <div className="skin-mailroom__stage" aria-label="Visual-engine animation stage reserved">
              <span className="skin-mailroom__route" aria-hidden="true" />
              <div className="skin-visual-reservation">
                <span>Visual engine stage</span>
                <strong>Agent courier motion reserved</strong>
                <small>Bette Davis Eyes × Gifted Animator</small>
              </div>
            </div>
            <section className="skin-mailroom__address skin-mailroom__address--to" aria-label="Dispatch recipient">
              <span>To</span>
              <strong>{humanize(latest.to)}</strong>
              <small>{latest.to}</small>
            </section>
            <article className="skin-mailroom__dispatch">
              <div>
                <SkinStatus label={humanize(latest.type)} tone={latest.type.includes("denied") || latest.type.includes("failed") ? "danger" : "info"} />
                <p>{latest.summary}</p>
              </div>
              <time>{formatTimestamp(latest.timestamp)}</time>
            </article>
          </div>
        ) : null}
      </QueryState>
    </SkinPanel>
  );
}
