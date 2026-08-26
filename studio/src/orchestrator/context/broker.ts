import { access, realpath } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";

export interface ContextScope {
  readAllowlist: string[];
  readDenylist: string[];
  writeAllowlist: string[];
  grantedProtectedPaths?: string[];
}

export interface ContextDecision {
  allowed: boolean;
  canonicalPath: string | null;
  reason: string;
}

function isInside(root: string, candidate: string): boolean {
  const pathFromRoot = relative(root, candidate);
  return pathFromRoot === "" || (!pathFromRoot.startsWith(`..${sep}`) && pathFromRoot !== ".." && !isAbsolute(pathFromRoot));
}

function normalizeRelative(root: string, candidate: string): string {
  return relative(root, candidate).split(sep).join("/");
}

function matchesScope(relativePath: string, scopes: readonly string[]): boolean {
  return scopes.some((scope) => {
    const normalized = scope.replace(/^\.\//, "").replace(/\/\*\*$/, "").replace(/\/$/, "");
    return relativePath === normalized || relativePath.startsWith(`${normalized}/`);
  });
}

export function isProtectedRelativePath(relativePath: string): boolean {
  const segments = relativePath.split("/");
  if (relativePath === ".env" || relativePath.startsWith(".env.")) return relativePath !== ".env.example";
  if (segments.includes("private")) return true;
  if (segments[0] === "credentials" || segments[0] === "secrets") return true;
  if (segments[0] === "research" && segments[1] === "audio") return true;
  if (segments[0] === "prompts" && segments[1] === "gpt_browser") return true;
  if (segments[0] === "plan" && segments[1] === "agents" && ["build_agents", "product_agents"].includes(segments[2] ?? "")) {
    return segments[4] === "context";
  }
  return false;
}

async function canonicalizeAllowingMissing(candidate: string): Promise<string> {
  let cursor = candidate;
  const missingSegments: string[] = [];

  while (true) {
    try {
      await access(cursor);
      const existingRealPath = await realpath(cursor);
      return resolve(existingRealPath, ...missingSegments.reverse());
    } catch {
      const parent = dirname(cursor);
      if (parent === cursor) throw new Error(`No existing ancestor for ${candidate}`);
      missingSegments.push(candidate.slice(parent.length + 1));
      candidate = parent;
      cursor = parent;
    }
  }
}

export class ContextBroker {
  readonly #root: string;

  private constructor(root: string) {
    this.#root = root;
  }

  static async create(repositoryRoot: string): Promise<ContextBroker> {
    return new ContextBroker(await realpath(repositoryRoot));
  }

  async authorizeRead(requestedPath: string, scope: ContextScope): Promise<ContextDecision> {
    return this.#authorize(requestedPath, scope.readAllowlist, scope.readDenylist, scope.grantedProtectedPaths ?? []);
  }

  async authorizeWrite(requestedPath: string, scope: ContextScope): Promise<ContextDecision> {
    return this.#authorize(requestedPath, scope.writeAllowlist, [], scope.grantedProtectedPaths ?? []);
  }

  async #authorize(requestedPath: string, allowlist: string[], denylist: string[], protectedGrants: string[]): Promise<ContextDecision> {
    const lexicalPath = resolve(this.#root, requestedPath);
    if (!isInside(this.#root, lexicalPath)) return { allowed: false, canonicalPath: null, reason: "path_escape" };

    const lexicalRelative = normalizeRelative(this.#root, lexicalPath);
    if (isProtectedRelativePath(lexicalRelative) && !matchesScope(lexicalRelative, protectedGrants)) {
      return { allowed: false, canonicalPath: lexicalPath, reason: "protected_context_requires_grant" };
    }

    const canonicalPath = await canonicalizeAllowingMissing(lexicalPath);
    if (!isInside(this.#root, canonicalPath)) return { allowed: false, canonicalPath, reason: "symlink_escape" };

    const canonicalRelative = normalizeRelative(this.#root, canonicalPath);
    if (matchesScope(canonicalRelative, denylist)) return { allowed: false, canonicalPath, reason: "explicit_deny" };
    if (!matchesScope(canonicalRelative, allowlist)) return { allowed: false, canonicalPath, reason: "not_allowlisted" };
    return { allowed: true, canonicalPath, reason: "allowlisted" };
  }
}

