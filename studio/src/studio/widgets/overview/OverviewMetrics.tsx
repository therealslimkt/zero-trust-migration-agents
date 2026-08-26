import { SkinPanel } from "../../../design-system/index.js";
import type { AgentSummary, ApprovalRequest, ProviderStatus, TaskEnvelope } from "../../../control/contracts.generated.js";

export interface OverviewMetricsProps {
  agents: AgentSummary[];
  providers: ProviderStatus[];
  tasks: TaskEnvelope[];
  approvals: ApprovalRequest[];
}

export function OverviewMetrics({ agents, providers, tasks, approvals }: OverviewMetricsProps) {
  const metrics = [
    { label: "Active workers", value: agents.filter((agent) => agent.status === "running").length, tone: "blue" },
    { label: "Queued tasks", value: tasks.filter((task) => task.status === "queued").length, tone: "butter" },
    { label: "Blocked tasks", value: tasks.filter((task) => task.status === "blocked").length, tone: "red" },
    { label: "Pending approvals", value: approvals.filter((approval) => approval.status === "pending").length, tone: "green" },
    { label: "Healthy providers", value: providers.filter((provider) => provider.health === "healthy").length, tone: "taupe" },
  ];

  return (
    <section className="skin-metric-grid" aria-label="Mission Control overview">
      {metrics.map((metric) => (
        <SkinPanel key={metric.label} title={metric.label} className={`skin-metric skin-metric--${metric.tone}`}>
          <strong className="skin-metric__value">{metric.value}</strong>
        </SkinPanel>
      ))}
    </section>
  );
}

