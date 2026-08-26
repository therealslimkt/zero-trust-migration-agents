import { SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import type { TaskStatus } from "../../../control/contracts.generated.js";
import { useTasks } from "../../shared/api/queries.js";
import { humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const columns: TaskStatus[] = ["proposed", "queued", "running", "blocked", "review", "ready", "complete", "failed", "cancelled"];
const tone = (status: TaskStatus): SkinStatusTone => status === "complete" || status === "ready" ? "success" : status === "running" ? "info" : status === "blocked" || status === "failed" ? "danger" : status === "review" ? "warning" : "neutral";

export function TaskBoard() {
  const query = useTasks();
  return (
    <SkinPanel title="Task board" description="The live Mission Control lifecycle" className="skin-widget skin-widget--wide">
      <QueryState pending={query.isPending} error={query.error} empty={query.data?.length === 0} emptyMessage="No tasks have been scheduled yet.">
        <div className="skin-task-board">
          {columns.map((status) => {
            const tasks = query.data?.filter((task) => task.status === status) ?? [];
            return (
              <section className="skin-task-column" key={status}>
                <header><span>{humanize(status)}</span><strong>{tasks.length}</strong></header>
                {tasks.map((task) => (
                  <article className="skin-task-card" key={task.taskId}>
                    <SkinStatus label={status} tone={tone(status)} />
                    <h3>{task.title}</h3>
                    <p>{task.ownerAgentId}</p>
                    <small>{task.branch ?? "Workspace pending"}</small>
                  </article>
                ))}
              </section>
            );
          })}
        </div>
      </QueryState>
    </SkinPanel>
  );
}

