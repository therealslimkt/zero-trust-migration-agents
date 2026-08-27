import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router";

import { RecordedDemoClient, WebApiError } from "../../client";
import { PixelIcon, ReplayBadge } from "../../shared/ui";
import { RecordedReplayPage } from "./RecordedReplayPage";

const demoClient = new RecordedDemoClient();

export function RecordedDemoRoute() {
  const { demoId } = useParams<{ demoId: string }>();
  const navigate = useNavigate();
  const query = useQuery({
    queryKey: ["recorded-demo", demoId],
    queryFn: () => demoClient.get(demoId!),
    enabled: Boolean(demoId),
    staleTime: Number.POSITIVE_INFINITY,
    retry: (attempt, error) => !(error instanceof WebApiError && error.status < 500) && attempt < 2,
  });

  if (!demoId) return <ReplayRouteState title="Replay route is incomplete" detail="No published demo identifier was provided." />;
  if (query.isPending) return <ReplayRouteState title="Verifying published bundle" detail="Loading its immutable synthetic replay manifest." busy />;
  if (query.isError) {
    const unavailable = query.error instanceof WebApiError && query.error.status === 404;
    return (
      <ReplayRouteState
        title={unavailable ? "Published replay not found" : "Replay service unavailable"}
        detail={unavailable ? "This route does not identify an owner-published demo." : "The recorded bundle could not be loaded. No substitute data is shown."}
        onBack={() => navigate("/")}
        onRetry={unavailable ? undefined : () => void query.refetch()}
      />
    );
  }
  return <RecordedReplayPage manifest={query.data} onExit={() => navigate("/")} />;
}

interface ReplayRouteStateProps {
  readonly title: string;
  readonly detail: string;
  readonly busy?: boolean;
  readonly onBack?: () => void;
  readonly onRetry?: () => void;
}

function ReplayRouteState({ title, detail, busy = false, onBack, onRetry }: ReplayRouteStateProps) {
  return (
    <main className="replay-route-state mission-control-root">
      <div className="replay-route-state__card">
        <ReplayBadge mode="replay" detail={busy ? "VERIFYING" : "LOCKED"} />
        <PixelIcon name={busy ? "radar" : "lock"} size="xl" color={busy ? "google-blue" : "google-yellow"} glow />
        <h1>{title}</h1>
        <p>{detail}</p>
        <div>
          {onRetry ? <button className="replay-button replay-button--primary" onClick={onRetry}>Try again</button> : null}
          {onBack ? <button className="replay-button" onClick={onBack}>Return home</button> : null}
        </div>
      </div>
    </main>
  );
}
