import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadRuntimeConfig } from "../config/runtime.js";
import { runMigrations } from "../persistence/migrate.js";
import { createDatabasePool } from "../persistence/postgres.js";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));
const config = loadRuntimeConfig();
const pool = createDatabasePool(config.databaseUrl);

try {
  await runMigrations(pool, resolve(moduleDirectory, "../persistence/migrations"));
  console.log("Skin Mission Control migrations complete.");
} finally {
  await pool.end();
}
