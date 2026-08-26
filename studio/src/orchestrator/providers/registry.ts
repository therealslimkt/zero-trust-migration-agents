import type { ProviderDefinition } from "./types.js";

export const PROVIDERS: readonly ProviderDefinition[] = [
  {
    id: "codex",
    displayName: "Codex",
    executable: "/opt/homebrew/bin/codex",
    versionArgs: ["--version"],
    authProbe: { args: ["login", "status"], authenticatedPattern: /logged in/i },
  },
  {
    id: "antigravity",
    displayName: "Antigravity",
    executable: "/Users/kohalloran/.local/bin/agy",
    versionArgs: ["--version"],
  },
  {
    id: "claude",
    displayName: "Claude Code",
    executable: "/opt/homebrew/bin/claude",
    versionArgs: ["--version"],
    authProbe: { args: ["auth", "status"], authenticatedPattern: /loggedIn[^a-z]+true/i },
  },
] as const;

