import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";

import { ContextBroker, type ContextScope } from "../context/broker.js";

const execFileAsync = promisify(execFile);

export interface AntigravityResult {
  conversationId: string;
  response: string;
  durationSeconds: number;
  usage: {
    inputTokens: number;
    outputTokens: number;
    thinkingTokens: number;
    cacheReadTokens: number;
    totalTokens: number;
  };
}

interface RawAntigravityResult {
  conversation_id: string;
  status: "SUCCESS" | "ERROR";
  response: string;
  error?: string;
  duration_seconds: number;
  usage: {
    input_tokens: number;
    output_tokens: number;
    thinking_tokens: number;
    cache_read_tokens: number;
    total_tokens: number;
  };
}

export interface AntigravityReviewOptions {
  executable: string;
  repositoryRoot: string;
  capsuleRoot: string;
  contextPaths: string[];
  scope: ContextScope;
  instructions: string;
  model: string;
  timeoutMs?: number;
}

export function buildAntigravityArgs(prompt: string, model: string, timeoutMs = 180_000): string[] {
  const effort = model.match(/-(low|medium|high)$/)?.[1];
  if (!effort) throw new Error(`Antigravity model must encode its effort suffix: ${model}`);
  return [
    "--print",
    prompt,
    "--sandbox",
    "--mode",
    "plan",
    "--model",
    model,
    "--effort",
    effort,
    "--output-format",
    "json",
    "--print-timeout",
    `${Math.ceil(timeoutMs / 1_000)}s`,
  ];
}

export async function buildBrokeredPrompt(options: AntigravityReviewOptions): Promise<string> {
  const broker = await ContextBroker.create(options.repositoryRoot);
  const sections: string[] = [];
  for (const contextPath of options.contextPaths) {
    const decision = await broker.authorizeRead(contextPath, options.scope);
    if (!decision.allowed || !decision.canonicalPath) {
      throw new Error(`Context Broker denied ${contextPath}: ${decision.reason}`);
    }
    sections.push(`FILE: ${contextPath}\n---\n${await readFile(decision.canonicalPath, "utf8")}\n---`);
  }
  return [
    options.instructions,
    "Use only the exact broker-approved file contents below.",
    "Do not use tools, commands, filesystem access, network research, or hidden context.",
    ...sections,
  ].join("\n\n");
}

export async function runAntigravityReview(options: AntigravityReviewOptions): Promise<AntigravityResult> {
  const timeoutMs = options.timeoutMs ?? 180_000;
  const prompt = await buildBrokeredPrompt(options);
  const { stdout } = await execFileAsync(
    options.executable,
    buildAntigravityArgs(prompt, options.model, timeoutMs),
    {
      cwd: options.capsuleRoot,
      env: process.env,
      timeout: timeoutMs + 5_000,
      maxBuffer: 4 * 1024 * 1024,
    },
  );
  const raw = JSON.parse(stdout.trim()) as RawAntigravityResult;
  if (raw.status !== "SUCCESS" || !raw.response.trim()) {
    throw new Error(`Antigravity review failed: ${raw.error ?? "empty response"}`);
  }
  return {
    conversationId: raw.conversation_id,
    response: raw.response,
    durationSeconds: raw.duration_seconds,
    usage: {
      inputTokens: raw.usage.input_tokens,
      outputTokens: raw.usage.output_tokens,
      thinkingTokens: raw.usage.thinking_tokens,
      cacheReadTokens: raw.usage.cache_read_tokens,
      totalTokens: raw.usage.total_tokens,
    },
  };
}
