import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));

export interface RuntimeConfig {
  host: string;
  port: number;
  repositoryRoot: string;
  runtimeDirectory: string;
  eventLedgerPath: string;
  databaseUrl: string;
}

export function loadRuntimeConfig(environment: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const repositoryRoot = resolve(environment.SKIN_REPOSITORY_ROOT ?? resolve(moduleDirectory, "../../../.."));
  const runtimeDirectory = resolve(repositoryRoot, ".orchestrator/runtime");

  return {
    host: environment.SKIN_HOST ?? "127.0.0.1",
    port: Number.parseInt(environment.SKIN_PORT ?? "4317", 10),
    repositoryRoot,
    runtimeDirectory,
    eventLedgerPath: resolve(runtimeDirectory, "events.jsonl"),
    databaseUrl: environment.SKIN_DATABASE_URL ?? "postgresql:///skin_dev",
  };
}

