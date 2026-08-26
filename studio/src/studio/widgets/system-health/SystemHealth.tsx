import { SignalPulse, SkinPanel, SkinStatus } from "../../../design-system/index.js";
import { useSystemStatus } from "../../shared/api/queries.js";
import { formatBytes, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

export function SystemHealth() {
  const query = useSystemStatus();
  return (
    <SkinPanel title="System health" description="Enough telemetry to protect the local machine" className="skin-widget">
      <QueryState pending={query.isPending} error={query.error} empty={!query.data}>
        {query.data ? (
          <div className="skin-system-grid">
            <SignalPulse active={query.data.status === "healthy"} label={humanize(query.data.status)} />
            <dl>
              <div><dt>CPU</dt><dd>{query.data.cpuPercent.toFixed(1)}%</dd></div>
              <div><dt>Memory</dt><dd>{formatBytes(query.data.memoryUsedBytes)} / {formatBytes(query.data.memoryTotalBytes)}</dd></div>
              <div><dt>Workers</dt><dd>{query.data.activeWorkers}</dd></div>
            </dl>
            <div className="skin-service-list">
              {Object.entries(query.data.services).map(([service, status]) => <span key={service}>{humanize(service)} <SkinStatus label={status} tone={status === "healthy" ? "success" : status === "unavailable" ? "danger" : "warning"} /></span>)}
            </div>
          </div>
        ) : null}
      </QueryState>
    </SkinPanel>
  );
}

