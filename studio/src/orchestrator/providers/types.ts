import type { ProviderId, ProviderStatus } from "../../control/contracts.generated.js";

export interface ProviderDefinition {
  id: ProviderId;
  displayName: string;
  executable: string;
  versionArgs: string[];
  authProbe?: {
    args: string[];
    authenticatedPattern: RegExp;
  };
}

export interface ProviderAdapter {
  readonly definition: ProviderDefinition;
  health(): Promise<ProviderStatus>;
}

