import { SkinPanel, SkinStatus } from "../../../design-system/index.js";
import { useFeedback } from "../../shared/api/queries.js";
import { formatTimestamp } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

export function FeedbackLoop() {
  const query = useFeedback();
  return (
    <SkinPanel title="Feedback loop" description="Evidence before durable agent learning" className="skin-widget">
      <QueryState pending={query.isPending} error={query.error} empty={(query.data?.data.length ?? 0) === 0} emptyMessage="No feedback has been captured yet.">
        <div className="skin-row-list">
          {query.data?.data.map((feedback) => (
            <article className="skin-data-row" key={feedback.feedbackId}>
              <div><strong>{feedback.subjectAgentId}</strong><p>{feedback.summary}</p></div>
              <div className="skin-data-row__end"><SkinStatus label={feedback.promotionStatus} tone={feedback.promotionStatus === "promoted" ? "success" : "neutral"} /><small>{formatTimestamp(feedback.createdAt)}</small></div>
            </article>
          ))}
          {(query.data?.candidates.length ?? 0) > 0 ? <p className="skin-candidate-count">{query.data?.candidates.length} lesson candidates require human review.</p> : null}
        </div>
      </QueryState>
    </SkinPanel>
  );
}
