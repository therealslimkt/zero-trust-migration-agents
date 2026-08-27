import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { LiveWebClient, WebApiError } from '../../client'
import type {
  CloudConnectionResponse,
  CloudSetupRequest,
  CloudSetupResponse,
  CloudVerifyResponse,
  DriverApprovalResponse,
  DriverCandidate,
  DriverResearchRequest,
  DriverResearchStatusResponse,
  ListLiveRunsResponse,
  LiveRunEvent,
  LiveSourceResponse,
  SourceId,
} from '../../contracts.generated'
import { WEB_SCHEMA_VERSION } from '../../contracts.generated'
import { useAuth } from '../../features/auth'
import { CloudSettingsPage } from './CloudSettingsPage'
import { DashboardPage } from './DashboardPage'
import { SourceDetailPage, type SourcePane } from './SourceDetailPage'
import { SourceOnboardingPage } from './SourceOnboardingPage'
import type { ConnectionState, ResourceState } from './state'

function message(error: unknown): string {
  if (error instanceof WebApiError) return error.problem?.detail ?? error.message
  return error instanceof Error ? error.message : 'The authenticated web service could not complete the request.'
}

function useLiveClient(): LiveWebClient {
  const { getIdToken } = useAuth()
  return useMemo(() => new LiveWebClient(() => getIdToken()), [getIdToken])
}

function queryState<T>(query: { readonly isPending: boolean; readonly isError: boolean; readonly error: unknown; readonly data?: T; readonly dataUpdatedAt: number; readonly isFetching: boolean }, empty?: (data: T) => boolean): ResourceState<T> {
  if (query.isPending) return { status: 'loading', connection: 'live' }
  if (query.isError) return { status: 'error', connection: navigator.onLine ? 'reconnecting' : 'offline', message: message(query.error) }
  if (query.data === undefined || empty?.(query.data)) return { status: 'empty', connection: 'live' }
  return { status: 'ready', data: query.data, connection: query.isFetching ? 'reconnecting' : 'live', stale: query.isFetching, lastUpdatedAt: new Date(query.dataUpdatedAt).toISOString() }
}

export function DashboardRoute() {
  const client = useLiveClient()
  const navigate = useNavigate()
  const query = useQuery({ queryKey: ['live-runs'], queryFn: () => client.listRuns(), refetchInterval: 10_000 })
  return <DashboardPage runs={queryState(query, (data) => data.runs.length === 0)} onRetry={() => void query.refetch()} onCreateRun={() => navigate('/sources/new')} onOpenRun={(runId) => navigate(`/runs/${encodeURIComponent(runId)}`)} onOpenSource={(runId, sourceId) => navigate(`/runs/${encodeURIComponent(runId)}/sources/${sourceId}`)} />
}

export function LiveRunRoute() {
  const client = useLiveClient()
  const navigate = useNavigate()
  const { runId } = useParams<{ runId: string }>()
  const query = useQuery({ queryKey: ['live-run', runId], queryFn: () => client.getRun(runId!), enabled: Boolean(runId), refetchInterval: 10_000 })
  const state = queryState(query)
  const runs: ResourceState<ListLiveRunsResponse> = state.status === 'ready'
    ? { ...state, data: { schemaVersion: '1.0.0', runs: [state.data] } }
    : state
  return <DashboardPage runs={runs} onRetry={() => void query.refetch()} onOpenSource={(ownedRunId, sourceId) => navigate(`/runs/${encodeURIComponent(ownedRunId)}/sources/${sourceId}`)} />
}

function parseEventBlock(block: string): { readonly id?: string; readonly event?: LiveRunEvent } {
  let id: string | undefined
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith('id:')) id = line.slice(3).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  if (!data.length) return { id }
  try { return { id, event: JSON.parse(data.join('\n')) as LiveRunEvent } } catch { return { id } }
}

function useRunEvents(client: LiveWebClient, runId?: string) {
  const [events, setEvents] = useState<readonly LiveRunEvent[]>([])
  const [connection, setConnection] = useState<ConnectionState>('reconnecting')
  const lastEventId = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (!runId) return
    const abort = new AbortController()
    let active = true
    const connect = async () => {
      while (active) {
        try {
          setConnection('reconnecting')
          const response = await client.openRunEvents(runId, lastEventId.current, abort.signal)
          if (!response.body) throw new Error('The event stream has no response body.')
          setConnection('live')
          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          while (active) {
            const chunk = await reader.read()
            if (chunk.done) break
            buffer += decoder.decode(chunk.value, { stream: true }).replace(/\r\n/g, '\n')
            let boundary = buffer.indexOf('\n\n')
            while (boundary >= 0) {
              const parsed = parseEventBlock(buffer.slice(0, boundary))
              buffer = buffer.slice(boundary + 2)
              if (parsed.id) lastEventId.current = parsed.id
              if (parsed.event) setEvents((current) => current.some((item) => item.eventId === parsed.event!.eventId) ? current : [...current, parsed.event!])
              boundary = buffer.indexOf('\n\n')
            }
          }
        } catch {
          if (!active || abort.signal.aborted) return
          setConnection(navigator.onLine ? 'reconnecting' : 'offline')
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500))
      }
    }
    void connect()
    return () => { active = false; abort.abort() }
  }, [client, runId])
  return { events, connection }
}

const sourceIds: readonly SourceId[] = ['jde', 'maxdb', 'btrieve']

export function SourceDetailRoute() {
  const client = useLiveClient()
  const { runId, sourceId } = useParams<{ runId: string; sourceId: string }>()
  const validSourceId = sourceIds.includes(sourceId as SourceId) ? sourceId as SourceId : undefined
  const query = useQuery({ queryKey: ['live-source', runId, validSourceId], queryFn: () => client.getSource(runId!, validSourceId!), enabled: Boolean(runId && validSourceId), refetchInterval: 10_000 })
  const stream = useRunEvents(client, runId)
  const [pane, setPane] = useState<SourcePane>('source')
  const invalid: ResourceState<LiveSourceResponse> = { status: 'error', connection: 'offline', message: 'The route does not identify a supported migration source.' }
  const state = validSourceId ? queryState(query) : invalid
  const connectedState = state.status === 'ready' ? { ...state, connection: stream.connection } : state
  return <SourceDetailPage source={connectedState} events={stream.events} activePane={pane} onActivePaneChange={setPane} onRetry={() => void query.refetch()} onCopy={(value) => void navigator.clipboard.writeText(value)} />
}

const emptyCloudSetup: CloudSetupRequest = { schemaVersion: WEB_SCHEMA_VERSION, projectId: '', region: '', datasetPrefix: '' }

export function CloudSettingsRoute() {
  const client = useLiveClient()
  const cache = useQueryClient()
  const connection = useQuery({ queryKey: ['cloud-connection'], queryFn: () => client.getCloudConnection() })
  const [setupRequest, setSetupRequest] = useState(emptyCloudSetup)
  const [setup, setSetup] = useState<ResourceState<CloudSetupResponse>>({ status: 'empty', connection: 'live' })
  const [receipt, setReceipt] = useState('')
  const [verification, setVerification] = useState<ResourceState<CloudVerifyResponse>>({ status: 'empty', connection: 'live' })
  const setupMutation = useMutation({ mutationFn: (request: CloudSetupRequest) => client.createCloudSetup(request), onMutate: () => setSetup({ status: 'loading', connection: 'live' }), onSuccess: (data) => setSetup({ status: 'ready', data, connection: 'live', lastUpdatedAt: new Date().toISOString() }), onError: (error) => setSetup({ status: 'error', message: message(error), connection: 'live' }) })
  const verifyMutation = useMutation({ mutationFn: ({ setupId, value }: { setupId: string; value: string }) => client.verifyCloudSetup({ schemaVersion: WEB_SCHEMA_VERSION, setupId, receipt: value }), onMutate: () => setVerification({ status: 'loading', connection: 'live' }), onSuccess: (data) => { setReceipt(''); setVerification({ status: 'ready', data, connection: 'live', lastUpdatedAt: new Date().toISOString() }); void cache.invalidateQueries({ queryKey: ['cloud-connection'] }) }, onError: (error) => { setReceipt(''); setVerification({ status: 'error', message: message(error), connection: 'live' }) } })
  const connectionState = queryState<CloudConnectionResponse>(connection)
  return <CloudSettingsPage connection={connectionState} setupRequest={setupRequest} setup={setup} receipt={receipt} verification={verification} submitting={setupMutation.isPending || verifyMutation.isPending} onSetupRequestChange={setSetupRequest} onReceiptChange={setReceipt} onGenerateSetup={(request) => setupMutation.mutate(request)} onVerify={(setupId, value) => verifyMutation.mutate({ setupId, value })} onCopyCommand={(command) => void navigator.clipboard.writeText(command)} />
}

const emptyResearch: DriverResearchRequest = { schemaVersion: WEB_SCHEMA_VERSION, projectId: '', databaseFamily: '', databaseVersion: '', applicationLayer: '', javaRuntime: '', connectivityMode: 'tailscale' }

export function SourceOnboardingRoute() {
  const client = useLiveClient()
  const navigate = useNavigate()
  const cloud = useQuery({ queryKey: ['cloud-connection'], queryFn: () => client.getCloudConnection() })
  const [request, setRequest] = useState(emptyResearch)
  const [researchId, setResearchId] = useState<string>()
  const [approval, setApproval] = useState<DriverApprovalResponse>()
  const research = useQuery({ queryKey: ['driver-research', researchId], queryFn: () => client.getDriverResearch(researchId!), enabled: Boolean(researchId), refetchInterval: (query) => { const status = query.state.data?.status; return status === 'completed' || status === 'failed' ? false : 1500 } })
  const start = useMutation({ mutationFn: (value: DriverResearchRequest) => client.researchDrivers(value), onSuccess: (data) => setResearchId(data.researchId) })
  const approve = useMutation({ mutationFn: ({ candidate, status }: { candidate: DriverCandidate; status: DriverResearchStatusResponse }) => client.approveDriver(status.researchId, { schemaVersion: WEB_SCHEMA_VERSION, researchId: status.researchId, candidateId: candidate.candidateId, evidenceDigest: status.result!.evidenceDigest }), onSuccess: setApproval })
  let researchState: ResourceState<DriverResearchStatusResponse> = { status: 'empty', connection: 'live' }
  if (start.isPending || (researchId && research.isPending)) researchState = { status: 'loading', connection: 'live' }
  else if (start.isError) researchState = { status: 'error', connection: 'live', message: message(start.error) }
  else if (researchId) researchState = queryState(research)
  const current = research.data
  return <SourceOnboardingPage cloud={queryState(cloud)} request={request} research={researchState} approval={approval} submitting={start.isPending || approve.isPending} onRequestChange={setRequest} onStartResearch={(value) => start.mutate(value)} onApproveCandidate={current?.status === 'completed' && current.result ? (candidate) => approve.mutate({ candidate, status: current }) : undefined} onRetry={() => { if (researchId) void research.refetch(); else start.reset() }} onOpenCloudSettings={() => navigate('/settings/cloud')} />
}
