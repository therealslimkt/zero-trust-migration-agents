import { SkinButton } from "../../design-system/index.js";
import { AgentDetailPage } from "../pages/agents/AgentDetailPage.js";
import { OverviewPage } from "../pages/overview/OverviewPage.js";
import {
  AgentsPage,
  ApprovalsPage,
  ArtifactsPage,
  CommunicationsPage,
  ContextPage,
  FeedbackPage,
  ProvidersPage,
  SystemPage,
  TasksPage,
} from "../pages/sections/SectionPages.js";
import { useEventStream } from "../shared/api/useEventStream.js";
import { type StudioLocation, useStudioLocation } from "../shared/model/router.js";
import { useUiStore } from "../shared/model/uiStore.js";

const navigation = [
  ["Overview", "overview"],
  ["Providers", "providers"],
  ["Tasks", "tasks"],
  ["Agents", "agents"],
  ["A2A", "communications"],
  ["Context", "context"],
  ["Approvals", "approvals"],
  ["Artifacts", "artifacts"],
  ["Feedback", "feedback"],
  ["System", "system"],
] as const;

function CurrentPage({ location }: { location: StudioLocation }) {
  if (location.section === "agents" && location.agentId) return <AgentDetailPage agentId={location.agentId} />;

  switch (location.section) {
    case "providers": return <ProvidersPage />;
    case "tasks": return <TasksPage />;
    case "agents": return <AgentsPage />;
    case "communications": return <CommunicationsPage />;
    case "context": return <ContextPage />;
    case "approvals": return <ApprovalsPage />;
    case "artifacts": return <ArtifactsPage />;
    case "feedback": return <FeedbackPage />;
    case "system": return <SystemPage />;
    default: return <OverviewPage />;
  }
}

export function App() {
  useEventStream();
  const location = useStudioLocation();
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const density = useUiStore((state) => state.density);
  const toggleDensity = useUiStore((state) => state.toggleDensity);

  return (
    <div className="skin-studio" data-density={density}>
      <header className="skin-topbar">
        <a className="skin-brand" href="#/overview" aria-label="Skin Studio Mission Control home">
          <span className="skin-brand__mark" aria-hidden="true">S</span>
          <span><strong>Skin Studio</strong><small>Mission Control</small></span>
        </a>
        <nav aria-label="Mission Control sections">
          {navigation.map(([label, id]) => (
            <a
              className={location.section === id ? "is-active" : undefined}
              key={id}
              href={`#/${id}`}
              aria-current={location.section === id ? "page" : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
        <div className="skin-topbar__actions">
          <SkinButton size="sm" variant="tertiary" onPress={toggleDensity}>{density === "comfortable" ? "Compact" : "Comfortable"}</SkinButton>
          <SkinButton size="sm" variant="secondary" onPress={() => setTheme(theme === "skin-day" ? "skin-night" : "skin-day")}>{theme === "skin-day" ? "Night" : "Day"}</SkinButton>
        </div>
      </header>
      <CurrentPage location={location} />
    </div>
  );
}
