import { useQuery } from '@tanstack/react-query'

import type { LiveWebClient } from '../../client'
import { WORKFLOW_EVIDENCE_UNAVAILABLE, type WorkflowEvidenceProjection } from './projection'

/**
 * Optional persisted-evidence query. It never derives a projection from
 * events, timestamps, or UI state; unavailable is the only fallback.
 */
export function useWorkflowEvidenceProjection(client: LiveWebClient, runId?: string) {
  const query = useQuery({
    queryKey: ['workflow-evidence', runId],
    queryFn: () => client.getWorkflowEvidenceProjection(runId!),
    enabled: Boolean(runId),
    retry: false,
    staleTime: 10_000,
  })
  const evidence: WorkflowEvidenceProjection = query.data ?? WORKFLOW_EVIDENCE_UNAVAILABLE
  return { evidence, isLoading: query.isPending, isUnavailable: evidence.status === 'unavailable', refetch: query.refetch }
}
