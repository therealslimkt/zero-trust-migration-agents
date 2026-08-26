import { SkinPanel } from "../../../design-system/index.js";
import { useAgents, useApprovals, useArtifacts, useEvents, useFeedback } from "../../shared/api/queries.js";
import { PageHeader } from "../../shared/ui/PageHeader.js";
import { RoutePage } from "../../shared/ui/RoutePage.js";
import { A2AMailroom } from "../../widgets/a2a-mailroom/A2AMailroom.js";
import { AgentRegistry } from "../../widgets/agent-registry/AgentRegistry.js";
import { ApprovalQueue } from "../../widgets/approval-queue/ApprovalQueue.js";
import { ArtifactList } from "../../widgets/artifact-list/ArtifactList.js";
import { ContextMonitor } from "../../widgets/context-monitor/ContextMonitor.js";
import { FeedbackLoop } from "../../widgets/feedback-loop/FeedbackLoop.js";
import { LiveEventStream } from "../../widgets/live-events/LiveEventStream.js";
import { ProviderHealth } from "../../widgets/provider-health/ProviderHealth.js";
import { SystemHealth } from "../../widgets/system-health/SystemHealth.js";
import { TaskBoard } from "../../widgets/task-board/TaskBoard.js";

interface RouteStat {
  label: string;
  value: number | string;
  tone?: "blue" | "red" | "green";
}

function RouteStats({ stats }: { stats: RouteStat[] }) {
  return (
    <section className="skin-route-stats" aria-label="Section summary">
      {stats.map((stat) => (
        <article className={`skin-route-stat skin-route-stat--${stat.tone ?? "blue"}`} key={stat.label}>
          <strong>{stat.value}</strong>
          <span>{stat.label}</span>
        </article>
      ))}
    </section>
  );
}

export function ProvidersPage() {
  return (
    <RoutePage routeKey="providers">
      <PageHeader eyebrow="Runtime routes" title="Providers" description="Executable discovery, authentication, model routing, and invocation readiness—separate from agent identity." />
      <section className="skin-content-grid"><ProviderHealth /><SystemHealth /></section>
    </RoutePage>
  );
}

export function TasksPage() {
  return (
    <RoutePage routeKey="tasks">
      <PageHeader eyebrow="Execution lifecycle" title="Tasks" description="Follow every bounded assignment from proposal through review, readiness, and completion." />
      <TaskBoard />
    </RoutePage>
  );
}

export function AgentsPage() {
  const agents = useAgents();

  return (
    <RoutePage routeKey="agents">
      <PageHeader eyebrow="The company" title="Agents" description="Open any canonical identity to see its current cue, route, workspace, task reel, and mailbox." action={<span className="skin-header-note">{agents.data?.length ?? "—"} canonical identities</span>} />
      <AgentRegistry />
    </RoutePage>
  );
}

export function CommunicationsPage() {
  const events = useEvents();
  const approvals = events.data?.filter((event) => event.requiresHumanApproval).length ?? 0;
  const activeTraces = new Set(events.data?.map((event) => event.traceId) ?? []).size;

  return (
    <RoutePage routeKey="communications">
      <PageHeader eyebrow="Agent-to-agent mail" title="A2A Communications" description="Watch work move between identities as friendly, inspectable dispatches—not an opaque machine conversation." accent="red" />
      <RouteStats stats={[{ label: "Recorded dispatches", value: events.data?.length ?? "—" }, { label: "Active traces", value: activeTraces }, { label: "Human gates", value: approvals, tone: "red" }]} />
      <div className="skin-route-stack"><A2AMailroom /><LiveEventStream /></div>
    </RoutePage>
  );
}

export function ContextPage() {
  const events = useEvents();
  const contextEvents = events.data?.filter((event) => event.type.startsWith("context.")) ?? [];
  const grants = contextEvents.filter((event) => event.type === "context.grant").length;
  const denials = contextEvents.filter((event) => event.type === "context.denied").length;

  return (
    <RoutePage routeKey="context">
      <PageHeader eyebrow="Least-privilege ledger" title="Context" description="See what agents asked to know, what the broker granted, and what stayed sealed." />
      <RouteStats stats={[{ label: "Context decisions", value: contextEvents.length }, { label: "Grants", value: grants, tone: "green" }, { label: "Protected denials", value: denials, tone: "red" }]} />
      <ContextMonitor />
    </RoutePage>
  );
}

export function ApprovalsPage() {
  const approvals = useApprovals();
  const pending = approvals.data?.filter((approval) => approval.status === "pending").length ?? 0;
  const elevated = approvals.data?.filter((approval) => approval.risk === "high" || approval.risk === "critical").length ?? 0;

  return (
    <RoutePage routeKey="approvals">
      <PageHeader eyebrow="Founder authority" title="Approvals" description="Consequential actions stop here until a human makes the call." accent="red" />
      <RouteStats stats={[{ label: "Pending decisions", value: pending, tone: pending ? "red" : "green" }, { label: "High or critical risk", value: elevated, tone: elevated ? "red" : "blue" }, { label: "Default posture", value: "Stop" }]} />
      <ApprovalQueue />
    </RoutePage>
  );
}

export function ArtifactsPage() {
  const artifacts = useArtifacts();
  const valid = artifacts.data?.filter((artifact) => artifact.validationStatus === "valid").length ?? 0;
  const ready = artifacts.data?.filter((artifact) => artifact.mergeReadiness === "ready").length ?? 0;

  return (
    <RoutePage routeKey="artifacts">
      <PageHeader eyebrow="Output ledger" title="Artifacts" description="Inspect generated work, validation state, review ownership, and merge readiness." />
      <RouteStats stats={[{ label: "Registered outputs", value: artifacts.data?.length ?? "—" }, { label: "Validated", value: valid, tone: "green" }, { label: "Merge ready", value: ready, tone: ready ? "green" : "blue" }]} />
      <ArtifactList />
    </RoutePage>
  );
}

export function FeedbackPage() {
  const feedback = useFeedback();
  const candidates = feedback.data?.candidates.length ?? 0;
  const promoted = feedback.data?.data.filter((record) => record.promotionStatus === "promoted").length ?? 0;

  return (
    <RoutePage routeKey="feedback">
      <PageHeader eyebrow="Learning with receipts" title="Feedback" description="Turn outcomes into durable lessons only when evidence and human review support the change." accent="green" />
      <RouteStats stats={[{ label: "Feedback records", value: feedback.data?.data.length ?? "—" }, { label: "Review candidates", value: candidates, tone: candidates ? "red" : "blue" }, { label: "Promoted lessons", value: promoted, tone: "green" }]} />
      <FeedbackLoop />
    </RoutePage>
  );
}

export function SystemPage() {
  return (
    <RoutePage routeKey="system">
      <PageHeader eyebrow="Local machine" title="System" description="Protect the workstation with a clear view of services, workers, CPU, and memory." />
      <section className="skin-content-grid"><SystemHealth /><SkinPanel title="Operating boundary" description="What this control room is allowed to do"><div className="skin-boundary-list"><p><strong>Local first.</strong> Services and records stay on the development machine.</p><p><strong>Human gated.</strong> Spend, release, and protected context require explicit authority.</p><p><strong>Observable.</strong> Every worker cue and decision produces inspectable state.</p></div></SkinPanel></section>
    </RoutePage>
  );
}
