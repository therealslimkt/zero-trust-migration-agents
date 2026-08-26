import { cpus, freemem, loadavg, totalmem } from "node:os";

import { CONTROL_SCHEMA_VERSION, type HealthStatus, type SystemStatus } from "../../control/contracts.generated.js";

function cpuPercent(): number {
  const oneMinuteLoad = loadavg()[0] ?? 0;
  return Math.min(100, Math.round((oneMinuteLoad / Math.max(1, cpus().length)) * 10_000) / 100);
}

export function getSystemStatus(
  counters: Pick<SystemStatus, "activeWorkers" | "queuedTasks" | "pendingApprovals">,
  services: Record<string, HealthStatus>,
): SystemStatus {
  const memoryTotalBytes = totalmem();
  return {
    schemaVersion: CONTROL_SCHEMA_VERSION,
    status: Object.values(services).includes("unavailable") ? "degraded" : "healthy",
    ...counters,
    cpuPercent: cpuPercent(),
    memoryUsedBytes: memoryTotalBytes - freemem(),
    memoryTotalBytes,
    services,
    updatedAt: new Date().toISOString(),
  };
}
