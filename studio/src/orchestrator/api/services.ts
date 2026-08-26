import type { AgentSummary, ProviderStatus } from "../../control/contracts.generated.js";
import type { EventService } from "../events/service.js";
import type { ControlRepository } from "../persistence/controlRepository.js";
import type { ProviderDefinition } from "../providers/types.js";

export interface OrchestratorServices {
  agents: AgentSummary[];
  providers: readonly ProviderDefinition[];
  providerCache: Map<string, ProviderStatus>;
  repository: ControlRepository;
  events: EventService;
}

