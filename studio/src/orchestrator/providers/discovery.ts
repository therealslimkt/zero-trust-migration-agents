import { constants } from "node:fs";
import { access } from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { CONTROL_SCHEMA_VERSION, type ProviderStatus } from "../../control/contracts.generated.js";
import type { ProviderDefinition } from "./types.js";

const execFileAsync = promisify(execFile);

async function probe(definition: ProviderDefinition, args: string[]): Promise<string> {
  const { stdout, stderr } = await execFileAsync(definition.executable, args, {
    cwd: process.env.TMPDIR ?? "/tmp",
    timeout: 10_000,
    maxBuffer: 256 * 1024,
    encoding: "utf8",
    env: {
      HOME: process.env.HOME,
      PATH: process.env.PATH,
      TMPDIR: process.env.TMPDIR,
      USER: process.env.USER,
      NO_COLOR: "1",
    },
  });
  return `${stdout}\n${stderr}`.trim();
}

export async function discoverProvider(definition: ProviderDefinition): Promise<ProviderStatus> {
  const updatedAt = new Date().toISOString();

  try {
    await access(definition.executable, constants.X_OK);
  } catch {
    return {
      schemaVersion: CONTROL_SCHEMA_VERSION,
      providerId: definition.id,
      displayName: definition.displayName,
      discovery: "not_installed",
      executablePath: null,
      version: null,
      authentication: "unknown",
      health: "unavailable",
      error: `Executable is not accessible: ${definition.executable}`,
      updatedAt,
    };
  }

  try {
    const version = await probe(definition, definition.versionArgs);
    let authentication: ProviderStatus["authentication"] = definition.authProbe ? "unknown" : "authenticated";

    if (definition.authProbe) {
      try {
        const authOutput = await probe(definition, definition.authProbe.args);
        authentication = definition.authProbe.authenticatedPattern.test(authOutput) ? "authenticated" : "required";
      } catch {
        authentication = "required";
      }
    }

    return {
      schemaVersion: CONTROL_SCHEMA_VERSION,
      providerId: definition.id,
      displayName: definition.displayName,
      discovery: "available",
      executablePath: definition.executable,
      version: version.split("\n")[0] ?? version,
      authentication,
      health: authentication === "required" ? "degraded" : "healthy",
      updatedAt,
    };
  } catch (error) {
    return {
      schemaVersion: CONTROL_SCHEMA_VERSION,
      providerId: definition.id,
      displayName: definition.displayName,
      discovery: "broken",
      executablePath: definition.executable,
      version: null,
      authentication: "unknown",
      health: "unavailable",
      error: error instanceof Error ? error.message : String(error),
      updatedAt,
    };
  }
}

export async function discoverProviders(definitions: readonly ProviderDefinition[]): Promise<ProviderStatus[]> {
  return Promise.all(definitions.map(discoverProvider));
}
