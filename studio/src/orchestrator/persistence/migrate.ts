import { readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";

import type { DatabasePool } from "./postgres.js";
import { withTransaction } from "./postgres.js";

export async function runMigrations(pool: DatabasePool, migrationDirectory: string): Promise<void> {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS skin_schema_migrations (
      name text PRIMARY KEY,
      applied_at timestamptz NOT NULL DEFAULT now()
    )
  `);

  const files = (await readdir(migrationDirectory)).filter((file) => file.endsWith(".sql")).sort();
  const applied = new Set(
    (await pool.query<{ name: string }>("SELECT name FROM skin_schema_migrations")).rows.map((row) => row.name),
  );

  for (const file of files) {
    if (applied.has(file)) continue;
    const sql = await readFile(resolve(migrationDirectory, file), "utf8");
    await withTransaction(pool, async (client) => {
      await client.query(sql);
      await client.query("INSERT INTO skin_schema_migrations(name) VALUES ($1)", [file]);
    });
  }
}

