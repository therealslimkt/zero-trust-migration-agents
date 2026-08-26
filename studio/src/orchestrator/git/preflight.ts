import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

interface GitPolicy {
  branchPattern: string;
  forbidWritesOnBranches: string[];
  requireWorktreeBeforeWrite: boolean;
}

export interface GitPreflightResult {
  allowed: boolean;
  branch: string | null;
  repositoryRoot: string | null;
  reason: string;
}

async function git(cwd: string, args: string[]): Promise<string> {
  const { stdout } = await execFileAsync("git", args, { cwd, timeout: 5_000 });
  return stdout.trim();
}

export async function assertWriterWorkspace(cwd: string, policyPath: string): Promise<GitPreflightResult> {
  const policy = JSON.parse(await readFile(resolve(policyPath), "utf8")) as GitPolicy;

  try {
    const [repositoryRoot, branch, gitDirectory, commonDirectory] = await Promise.all([
      git(cwd, ["rev-parse", "--show-toplevel"]),
      git(cwd, ["branch", "--show-current"]),
      git(cwd, ["rev-parse", "--git-dir"]),
      git(cwd, ["rev-parse", "--git-common-dir"]),
    ]);

    if (!branch) return { allowed: false, branch: null, repositoryRoot, reason: "detached_head" };
    if (policy.forbidWritesOnBranches.includes(branch)) return { allowed: false, branch, repositoryRoot, reason: "protected_branch" };
    if (!new RegExp(policy.branchPattern).test(branch)) return { allowed: false, branch, repositoryRoot, reason: "invalid_branch_name" };
    if (policy.requireWorktreeBeforeWrite && resolve(cwd, gitDirectory) === resolve(cwd, commonDirectory)) {
      return { allowed: false, branch, repositoryRoot, reason: "task_worktree_required" };
    }

    return { allowed: true, branch, repositoryRoot, reason: "valid_writer_workspace" };
  } catch (error) {
    return {
      allowed: false,
      branch: null,
      repositoryRoot: null,
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}

