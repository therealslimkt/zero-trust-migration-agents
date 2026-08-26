import { SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import { useApprovals } from "../../shared/api/queries.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const tone = (risk: string): SkinStatusTone => risk === "critical" || risk === "high" ? "danger" : risk === "medium" ? "warning" : "neutral";

export function ApprovalQueue() {
  const query = useApprovals();
  return (
    <SkinPanel title="Approval queue" description="Founder-gated consequential actions" className="skin-widget">
      <QueryState pending={query.isPending} error={query.error} empty={query.data?.length === 0} emptyMessage="No approvals are pending.">
        <div className="skin-row-list">
          {query.data?.map((approval) => (
            <article className="skin-data-row" key={approval.approvalId}>
              <div><strong>{humanize(approval.action)}</strong><p>{approval.reason}</p></div>
              <div className="skin-data-row__end"><SkinStatus label={approval.risk} tone={tone(approval.risk)} /><small>{formatTimestamp(approval.createdAt)}</small></div>
            </article>
          ))}
        </div>
      </QueryState>
    </SkinPanel>
  );
}

