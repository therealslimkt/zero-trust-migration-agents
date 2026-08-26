import { SignalPulse, SkinPanel, SkinStatus, type SkinStatusTone } from "../../../design-system/index.js";
import { useProviders } from "../../shared/api/queries.js";
import { formatTimestamp } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

const tone = (health: string): SkinStatusTone => health === "healthy" ? "success" : health === "degraded" ? "warning" : health === "unavailable" ? "danger" : "neutral";

export function ProviderHealth() {
  const query = useProviders();
  return (
    <SkinPanel title="Provider health" description="Executable, authentication, and invocation readiness" className="skin-widget" >
      <QueryState pending={query.isPending} error={query.error} empty={query.data?.length === 0}>
        <div className="skin-row-list">
          {query.data?.map((provider) => (
            <article className="skin-data-row" key={provider.providerId}>
              <div>
                <SignalPulse active={provider.health === "healthy"} label={provider.displayName} />
                <p>{provider.version ?? "Version unavailable"}</p>
              </div>
              <div className="skin-data-row__end">
                <SkinStatus label={provider.health} tone={tone(provider.health)} />
                <small>{formatTimestamp(provider.lastInvocationAt)}</small>
              </div>
            </article>
          ))}
        </div>
      </QueryState>
    </SkinPanel>
  );
}

