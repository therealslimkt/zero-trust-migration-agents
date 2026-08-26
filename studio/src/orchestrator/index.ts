import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createApiServer } from "./api/server.js";
import { loadAgentRegistry } from "./agents/registry.js";
import { loadRuntimeConfig } from "./config/runtime.js";
import { ControlEventBus } from "./events/bus.js";
import { JsonlEventLedger } from "./events/ledger.js";
import { EventService } from "./events/service.js";
import { ControlRepository } from "./persistence/controlRepository.js";
import { runMigrations } from "./persistence/migrate.js";
import { createDatabasePool } from "./persistence/postgres.js";
import { PROVIDERS } from "./providers/registry.js";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));

export async function startMissionControl(): Promise<void> {
  const config = loadRuntimeConfig();
  const pool = createDatabasePool(config.databaseUrl);
  await runMigrations(pool, resolve(moduleDirectory, "persistence/migrations"));

  const repository = new ControlRepository(pool);
  const bus = new ControlEventBus();
  const events = new EventService(bus, new JsonlEventLedger(config.eventLedgerPath), (event) => repository.saveEvent(event));
  const agents = await loadAgentRegistry(
    resolve(config.repositoryRoot, "plan/agents/build_agents/build_agent_manifest.json"),
    resolve(config.repositoryRoot, "plan/agents/product_agents/product_agent_manifest.json"),
  );
  const app = await createApiServer({
    agents,
    providers: PROVIDERS,
    providerCache: new Map(),
    repository,
    events,
  });

  const stop = async (signal: string): Promise<void> => {
    app.log.info({ signal }, "stopping Mission Control");
    await app.close();
    await pool.end();
  };
  process.once("SIGINT", () => void stop("SIGINT"));
  process.once("SIGTERM", () => void stop("SIGTERM"));

  await app.listen({ host: config.host, port: config.port });
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startMissionControl().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
