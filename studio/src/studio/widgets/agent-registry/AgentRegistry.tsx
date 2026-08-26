import { SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import { deriveAgentActivity } from "../../entities/agent/model/activity.js";
import { useAgents, useTasks } from "../../shared/api/queries.js";
import { humanize } from "../../shared/lib/format.js";
import { agentHref } from "../../shared/model/router.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const tone = (status: string): SkinStatusTone => status === "running" ? "info" : status === "blocked" || status === "error" ? "danger" : status === "review" ? "warning" : status === "idle" ? "success" : "neutral";

export function AgentRegistry() {
  const query = useAgents();
  const tasks = useTasks();
  return (
    <SkinPanel title="Agent directory" description="Open any identity to inspect its cue, workspace, route, and recent signals" className="skin-widget">
      <QueryState pending={query.isPending || tasks.isPending} error={query.error ?? tasks.error} empty={query.data?.length === 0}>
        <div className="skin-agent-grid">
          {query.data?.map((agent) => {
            const activity = deriveAgentActivity(agent, tasks.data ?? []);
            return (
            <a className="skin-agent" href={agentHref(agent.id)} key={agent.id} aria-label={`Inspect ${agent.displayName}`}>
              <div className="skin-agent__content">
                <div className="skin-agent__heading">
                <div>
                  <h3>{agent.displayName}</h3>
                  <p>{humanize(agent.kind)} · {agent.id}</p>
                </div>
                  <SkinStatus label={activity.state} tone={tone(activity.state)} />
                </div>
                <p className="skin-agent__activity">{activity.label}</p>
                <span className="skin-agent__inspect">Open console <span aria-hidden="true">→</span></span>
              </div>
            </a>
          );})}
        </div>
      </QueryState>
    </SkinPanel>
  );
}
