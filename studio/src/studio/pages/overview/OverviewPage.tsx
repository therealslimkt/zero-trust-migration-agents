import { SkinPanel } from "../../../design-system/index.js";
import { useAgents, useApprovals, useProviders, useTasks } from "../../shared/api/queries.js";
import { PageHeader } from "../../shared/ui/PageHeader.js";
import { RoutePage } from "../../shared/ui/RoutePage.js";
import { OverviewMetrics } from "../../widgets/overview/OverviewMetrics.js";
import { SystemHealth } from "../../widgets/system-health/SystemHealth.js";

export function OverviewPage() {
  const agents = useAgents();
  const providers = useProviders();
  const tasks = useTasks();
  const approvals = useApprovals();
  const metricsReady = agents.data && providers.data && tasks.data && approvals.data;
  const routes = [
    { href: "#/tasks", label: "Follow execution", detail: `${tasks.data?.filter((task) => ["queued", "running", "review"].includes(task.status)).length ?? "—"} tasks in motion`, tone: "blue" },
    { href: "#/agents", label: "Meet the agents", detail: `${agents.data?.filter((agent) => agent.status === "running").length ?? "—"} currently working`, tone: "green" },
    { href: "#/context", label: "Inspect boundaries", detail: "Context grants and denials", tone: "blue" },
    { href: "#/approvals", label: "Make the call", detail: `${approvals.data?.filter((approval) => approval.status === "pending").length ?? "—"} decisions waiting`, tone: "red" },
  ];

  return (
    <RoutePage routeKey="overview">
      <PageHeader eyebrow="Local development operating environment" title="Every agent, cue, and decision in view." description="A concise read on Mission Control. Open a room when you want the full operational detail." action={<a className="skin-primary-link" href="#/communications">Enter the live mailroom →</a>} />

      {metricsReady ? <OverviewMetrics agents={agents.data} providers={providers.data} tasks={tasks.data} approvals={approvals.data} /> : <p className="skin-muted">Connecting to Mission Control…</p>}

      <section className="skin-overview-grid">
        <SkinPanel title="Choose a room" description="Each section is now its own focused workspace" className="skin-launchpad-panel">
          <div className="skin-launchpad">
            {routes.map((route) => (
              <a className={`skin-launchpad__route skin-launchpad__route--${route.tone}`} href={route.href} key={route.href}>
                <span>{route.label}</span><small>{route.detail}</small><strong aria-hidden="true">→</strong>
              </a>
            ))}
          </div>
        </SkinPanel>
        <SystemHealth />
      </section>
    </RoutePage>
  );
}
