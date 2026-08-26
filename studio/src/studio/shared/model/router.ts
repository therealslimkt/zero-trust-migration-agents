import { useSyncExternalStore } from "react";

export const studioSections = [
  "overview",
  "providers",
  "tasks",
  "agents",
  "communications",
  "context",
  "approvals",
  "artifacts",
  "feedback",
  "system",
] as const;

export type StudioSection = (typeof studioSections)[number];

export interface StudioLocation {
  section: StudioSection;
  agentId: string | null;
}

const sectionSet = new Set<string>(studioSections);

export function parseStudioHash(hash: string): StudioLocation {
  const [sectionCandidate = "overview", entityType, entityId] = hash.replace(/^#\/?/, "").split("/");
  const section = sectionSet.has(sectionCandidate) ? sectionCandidate as StudioSection : "overview";
  return {
    section,
    agentId: section === "agents" && entityType === "agent" && entityId ? decodeURIComponent(entityId) : null,
  };
}

function subscribe(onStoreChange: () => void): () => void {
  window.addEventListener("hashchange", onStoreChange);
  return () => window.removeEventListener("hashchange", onStoreChange);
}

function getSnapshot(): string {
  return window.location.hash;
}

export function useStudioLocation(): StudioLocation {
  return parseStudioHash(useSyncExternalStore(subscribe, getSnapshot, () => "#/overview"));
}

export function agentHref(agentId: string): string {
  return `#/agents/agent/${encodeURIComponent(agentId)}`;
}
