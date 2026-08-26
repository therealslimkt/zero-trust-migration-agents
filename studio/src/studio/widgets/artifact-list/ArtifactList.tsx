import { SkinPanel, SkinStatus } from "../../../design-system/index.js";
import { useArtifacts } from "../../shared/api/queries.js";
import { formatTimestamp, humanize } from "../../shared/lib/format.js";
import { QueryState } from "../../shared/ui/QueryState.js";

export function ArtifactList() {
  const query = useArtifacts();
  return (
    <SkinPanel title="Artifacts" description="Outputs, validation, review, and merge readiness" className="skin-widget">
      <QueryState pending={query.isPending} error={query.error} empty={query.data?.length === 0} emptyMessage="No task artifacts have been registered.">
        <div className="skin-row-list">
          {query.data?.map((artifact) => (
            <article className="skin-data-row" key={artifact.artifactId}>
              <div><strong>{humanize(artifact.kind)}</strong><p className="skin-mono">{artifact.path}</p></div>
              <div className="skin-data-row__end"><SkinStatus label={artifact.validationStatus} tone={artifact.validationStatus === "valid" ? "success" : artifact.validationStatus === "invalid" ? "danger" : "neutral"} /><small>{formatTimestamp(artifact.createdAt)}</small></div>
            </article>
          ))}
        </div>
      </QueryState>
    </SkinPanel>
  );
}

