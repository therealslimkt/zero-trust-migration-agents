import { SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import { deriveAgentActivity } from "../../entities/agent/model/activity.js";
import { useAgents, useEvents, useProviders, useTasks } from "../../shared/api/queries.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { PageHeader } from "../../shared/ui/PageHeader.js";
import { QueryState } from "../../shared/ui/QueryState.js";
import { RoutePage } from "../../shared/ui/RoutePage.js";

const tone = (status: string): SkinStatusTone => status === "running" ? "info" : status === "blocked" || status === "error" || status === "failed" ? "danger" : status === "review" ? "warning" : status === "complete" || status === "idle" ? "success" : "neutral";

export function AgentDetailPage({ agentId }: { agentId: string }) {
  const agents = useAgents();
  const tasks = useTasks();
  const events = useEvents();
  const providers = useProviders();
  const agent = agents.data?.find((candidate) => candidate.id === agentId);
  const relatedTasks = tasks.data?.filter((task) => task.ownerAgentId === agentId || task.reviewerAgentId === agentId) ?? [];
  const relatedTaskIds = new Set(relatedTasks.map((task) => task.taskId));
  const relatedEvents = events.data?.filter((event) => event.from === agentId || event.to === agentId || relatedTaskIds.has(event.taskId)).slice().reverse() ?? [];
  const activity = agent ? deriveAgentActivity(agent, tasks.data ?? []) : null;
  const provider = providers.data?.find((candidate) => candidate.providerId === agent?.activeProvider);

  return (
    <RoutePage routeKey={`agent-${agentId}`}>
      <PageHeader
        eyebrow="Agent console"
        title={agent?.displayName ?? humanize(agentId)}
        description="A live identity view: current cue, operating route, task history, and A2A mailbox."
        action={<a className="skin-text-link" href="#/agents">← All agents</a>}
      />
      <QueryState pending={agents.isPending || tasks.isPending || events.isPending} error={agents.error ?? tasks.error ?? events.error} empty={!agent} emptyMessage="That agent is not in the canonical registry.">
        {agent && activity ? (
          <div className="skin-agent-console">
            <SkinPanel title="Now on stage" description={activity.label} className="skin-agent-console__hero">
              <div className="skin-agent-stage">
                <div className="skin-visual-reservation skin-agent-stage__visual" aria-label="Visual-engine agent animation stage reserved">
                  <span>Visual engine stage</span>
                  <strong>{activity.state} identity motion</strong>
                  <small>Bette Davis Eyes × Gifted Animator</small>
                </div>
                <div className="skin-agent-stage__caption">
                  <SkinStatus label={activity.state} tone={tone(activity.state)} />
                  <strong>{activity.task?.title ?? "Standing by for Mission Control"}</strong>
                  <p>{activity.task?.objective ?? "Mailbox checked. Context sealed. Ready for the next cue."}</p>
                </div>
              </div>
            </SkinPanel>

            <SkinPanel title="Identity card" description="Stable persona, replaceable runtime route">
              <dl className="skin-detail-list">
                <div><dt>Canonical ID</dt><dd>{agent.id}</dd></div>
                <div><dt>Kind</dt><dd>{humanize(agent.kind)}</dd></div>
                <div><dt>Model policy</dt><dd>{agent.modelPolicy}</dd></div>
                <div><dt>Provider</dt><dd>{provider?.displayName ?? agent.activeProvider ?? "Assigned per task"}</dd></div>
                <div><dt>Workspace</dt><dd>{activity.task?.workspace ?? "No active workspace"}</dd></div>
                <div><dt>Context refs</dt><dd>{activity.task?.contextRefs?.length ?? 0} scoped references</dd></div>
              </dl>
            </SkinPanel>

            <SkinPanel title="Task reel" description="Owned and reviewed work" className="skin-agent-console__wide">
              {relatedTasks.length ? <div className="skin-row-list">{relatedTasks.map((task) => (
                <article className="skin-data-row" key={task.taskId}>
                  <div><strong>{task.title}</strong><p>{task.objective}</p></div>
                  <div className="skin-data-row__end"><SkinStatus label={task.status} tone={tone(task.status)} /><small>{formatTimestamp(task.createdAt)}</small></div>
                </article>
              ))}</div> : <p className="skin-empty-callout">No tasks yet. This agent is warmed up and awaiting its first cue.</p>}
            </SkinPanel>

            <SkinPanel title="A2A mailbox" description="Signals involving this identity" className="skin-agent-console__wide">
              {relatedEvents.length ? <ol className="skin-event-list">{relatedEvents.slice(0, 8).map((event) => (
                <li key={event.eventId}><time>{formatTimestamp(event.timestamp)}</time><div><SkinStatus label={humanize(event.type)} tone={tone(event.status)} /><p>{event.summary}</p><small>{event.from} → {event.to}</small></div></li>
              ))}</ol> : <p className="skin-empty-callout">Mailbox empty. The carrier will animate in when a new A2A event arrives.</p>}
            </SkinPanel>
          </div>
        ) : null}
      </QueryState>
    </RoutePage>
  );
}
