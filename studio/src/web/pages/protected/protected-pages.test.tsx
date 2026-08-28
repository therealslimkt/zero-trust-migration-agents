import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import {
  WEB_SCHEMA_VERSION,
  type CloudConnectionResponse,
  type CloudSetupRequest,
  type DriverResearchRequest,
  type DriverResearchStatusResponse,
  type ListLiveRunsResponse,
  type LiveRunEvent,
  type LiveSourceResponse,
  type SourceReplay,
} from '../../contracts.generated'
import { CloudSettingsPage } from './CloudSettingsPage'
import { DashboardPage } from './DashboardPage'
import { SourceDetailPage } from './SourceDetailPage'
import { SourceOnboardingPage } from './SourceOnboardingPage'

const VERIFIED_CLOUD: CloudConnectionResponse = {
  schemaVersion: WEB_SCHEMA_VERSION,
  status: 'verified',
  setupId: 'setup-123',
  projectId: 'operator-project',
  region: 'us-central1',
  datasetPrefix: 'migration',
  verifiedAt: '2026-08-27T10:00:00Z',
}

const RESEARCH_REQUEST: DriverResearchRequest = {
  schemaVersion: WEB_SCHEMA_VERSION,
  projectId: 'operator-project',
  databaseFamily: 'IBM Db2 for i',
  databaseVersion: '7.5',
  applicationLayer: 'JD Edwards World',
  javaRuntime: 'Java 17',
  connectivityMode: 'tailscale',
}

const RUNS: ListLiveRunsResponse = {
  schemaVersion: WEB_SCHEMA_VERSION,
  runs: [{
    schemaVersion: WEB_SCHEMA_VERSION,
    experienceMode: 'live',
    dataClass: 'private',
    runId: 'run-owned-1',
    portfolioName: 'Northwind migration',
    owner: {
      subject: 'subject-123',
      displayName: 'Verified Operator',
      email: 'verified.operator@example.com',
    },
    state: 'planning',
    updatedAt: '2026-08-27T10:00:00Z',
    sources: [
      { sourceId: 'jde', hostname: 'legacy-jde-db', state: 'planning', recordsRead: 12, recordsWritten: 0, recordsRejected: 0, evidenceReferences: [] },
      { sourceId: 'maxdb', hostname: 'legacy-maxdb', state: 'redacting', recordsRead: 8, recordsWritten: 0, recordsRejected: 0, evidenceReferences: [] },
      { sourceId: 'btrieve', hostname: 'legacy-btrieve-db', state: 'inventorying', recordsRead: 5, recordsWritten: 0, recordsRejected: 0, evidenceReferences: [] },
    ],
  }],
}

const EVIDENCE = {
  artifactId: 'artifact-1',
  kind: 'audit_log' as const,
  digest: 'sha256:evidence',
}

const SOURCE_REPLAY: SourceReplay = {
  sourceId: 'jde',
  hostname: 'legacy-jde-db',
  displayName: 'JD Edwards World',
  source: {
    databaseFamily: 'IBM Db2 for i',
    databaseVersion: '7.5',
    applicationLayer: 'JD Edwards World',
    schema: [{ name: 'AN8', dataType: 'packed decimal', nullable: false, description: 'Address number' }],
    samples: [{
      recordId: 'record-1',
      rawBytesHex: 'f1f2f3c4',
      decodedFields: [{ name: 'AN8', dataType: 'integer', value: 123 }],
    }],
    exampleQueries: ['SELECT AN8 FROM F0101 FETCH FIRST 5 ROWS ONLY'],
  },
  compiler: {
    actions: [{
      sequence: 1,
      eventId: 'compiler-event-1',
      timestamp: '2026-08-27T10:00:01Z',
      stage: 'protect',
      agent: 'edge-decoder',
      tool: 'local-gemma',
      summary: 'Decoded protected metadata',
      result: 'Validated field layout',
      evidenceReferences: [EVIDENCE],
    }],
    transforms: [{ sequence: 1, operation: 'packed_decimal', sourceField: 'AN8', targetField: 'address_number', targetType: 'INT64' }],
    driver: {
      coordinates: 'com.ibm.db2:jcc',
      version: '12.1.0',
      sourceUrl: 'https://example.com/official',
      license: 'Vendor license',
      sha256: 'sha256:driver',
      signatureVerified: true,
    },
    localGemmaEvidence: EVIDENCE,
    geminiVertexEvidence: { ...EVIDENCE, artifactId: 'artifact-vertex', kind: 'transform_plan' },
    beamTransformIds: ['beam-transform-1'],
    dataflowJobId: 'dataflow-job-1',
    approval: {
      approvalId: 'approval-1',
      decision: 'approved',
      decidedAt: '2026-08-27T10:01:00Z',
      planDigest: 'sha256:plan',
    },
  },
  destination: {
    dataset: 'legacy_migration',
    table: 'jde_f0101',
    schema: [{ name: 'address_number', dataType: 'INT64', nullable: false }],
    rows: [{ recordId: 'record-1', fields: [{ name: 'address_number', dataType: 'INT64', value: 123 }] }],
    reconciliation: {
      status: 'matched',
      recordsRead: 1,
      recordsWritten: 1,
      recordsRejected: 0,
      outputRows: 1,
      sourceChecksum: 'sha256:source',
      destinationChecksum: 'sha256:destination',
      evidence: { ...EVIDENCE, artifactId: 'artifact-reconciliation', kind: 'reconciliation' },
    },
    dataflowEvidence: { ...EVIDENCE, artifactId: 'artifact-dataflow', kind: 'dataflow_job' },
    bigQueryEvidence: { ...EVIDENCE, artifactId: 'artifact-bigquery', kind: 'bigquery_table' },
    suggestedQueries: ['SELECT * FROM `legacy_migration.jde_f0101` LIMIT 5'],
  },
}

const LIVE_SOURCE: LiveSourceResponse = {
  schemaVersion: WEB_SCHEMA_VERSION,
  experienceMode: 'live',
  dataClass: 'private',
  runId: 'run-owned-1',
  state: 'completed',
  sourceId: 'jde',
  hostname: 'legacy-jde-db',
  snapshotVersion: 7,
  updatedAt: '2026-08-27T10:02:00Z',
  progress: {
    sourceId: 'jde',
    hostname: 'legacy-jde-db',
    state: 'completed',
    recordsRead: 1,
    recordsWritten: 1,
    recordsRejected: 0,
    planDigest: 'sha256:plan',
    evidenceReferences: [EVIDENCE],
  },
  detail: SOURCE_REPLAY,
}

const EVENTS: readonly LiveRunEvent[] = [{
  schemaVersion: WEB_SCHEMA_VERSION,
  eventId: 'event-1',
  runId: 'run-owned-1',
  sequence: 1,
  timestamp: '2026-08-27T10:00:00Z',
  sourceId: 'jde',
  eventType: 'source.completed',
  state: 'completed',
  summary: 'Source migration reconciled',
  evidenceReferences: [EVIDENCE],
}]

describe('DashboardPage', () => {
  it('renders exact owned identity and three-source semantics with keyboard-accessible actions', async () => {
    const user = userEvent.setup()
    const openRun = vi.fn()
    const openSource = vi.fn()
    render(<DashboardPage runs={{ status: 'ready', data: RUNS }} onOpenRun={openRun} onOpenSource={openSource} />)

    expect(screen.getByLabelText('Owned by Verified Operator, verified.operator@example.com')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open JD Edwards World for run-owned-1' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open SAP ERP for run-owned-1' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open Sage ERP for run-owned-1' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Open mission control for Northwind migration' }))
    await user.click(screen.getByRole('button', { name: 'Open SAP ERP for run-owned-1' }))
    expect(openRun).toHaveBeenCalledWith('run-owned-1')
    expect(openSource).toHaveBeenCalledWith('run-owned-1', 'maxdb')
  })

  it('keeps stale data visible while reconnecting and reports incomplete portfolios', () => {
    const incomplete: ListLiveRunsResponse = {
      ...RUNS,
      runs: [{ ...RUNS.runs[0], sources: RUNS.runs[0].sources.slice(0, 2) }],
    }
    render(<DashboardPage runs={{ status: 'ready', data: incomplete, stale: true, connection: 'reconnecting', lastUpdatedAt: '2026-08-27T10:00:00Z' }} />)

    expect(screen.getByText('Reconnecting to the event stream')).toBeVisible()
    expect(screen.getByRole('alert')).toHaveTextContent('does not contain exactly one authenticated snapshot')
    expect(screen.getByText('No authenticated source snapshot was returned.')).toBeVisible()
  })

  it('renders honest loading, empty, and retryable error states', async () => {
    const user = userEvent.setup()
    const retry = vi.fn()
    const { rerender } = render(<DashboardPage runs={{ status: 'loading' }} />)
    expect(screen.getByText('Loading owned migrations')).toBeVisible()

    rerender(<DashboardPage runs={{ status: 'empty', message: 'Nothing belongs to this identity.' }} />)
    expect(screen.getByText('Nothing belongs to this identity.')).toBeVisible()

    rerender(<DashboardPage runs={{ status: 'error', message: 'Authenticated request failed.' }} onRetry={retry} />)
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(retry).toHaveBeenCalledOnce()
  })
})

describe('SourceOnboardingPage', () => {
  it('shows qualitative asynchronous research state without fake progress', () => {
    const running: DriverResearchStatusResponse = {
      schemaVersion: WEB_SCHEMA_VERSION,
      researchId: 'research-1',
      status: 'running',
      updatedAt: '2026-08-27T10:00:00Z',
    }
    render(
      <SourceOnboardingPage
        cloud={{ status: 'ready', data: VERIFIED_CLOUD }}
        request={RESEARCH_REQUEST}
        research={{ status: 'ready', data: running }}
        onRequestChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Research in progress')).toBeVisible()
    expect(screen.getByText(/No completion percentage is available/)).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('renders exact candidate evidence and offers the manual path for restricted drivers', async () => {
    const user = userEvent.setup()
    const approve = vi.fn()
    const manual = vi.fn()
    const completed: DriverResearchStatusResponse = {
      schemaVersion: WEB_SCHEMA_VERSION,
      researchId: 'research-1',
      status: 'completed',
      updatedAt: '2026-08-27T10:00:00Z',
      result: {
        schemaVersion: WEB_SCHEMA_VERSION,
        researchId: 'research-1',
        model: 'gemini-model-from-server',
        projectId: 'operator-project',
        createdAt: '2026-08-27T10:00:00Z',
        evidenceDigest: 'sha256:research',
        candidates: [{
          candidateId: 'candidate-1',
          coordinates: 'vendor:restricted-driver',
          version: '4.2',
          officialSource: 'Vendor portal',
          compatibility: 'Java 17',
          license: 'Commercial',
          redistribution: 'restricted',
          checksumAvailable: true,
          signatureAvailable: false,
          confidence: 0.82,
          caveats: ['Vendor entitlement required'],
        }],
      },
    }
    render(
      <SourceOnboardingPage
        cloud={{ status: 'ready', data: VERIFIED_CLOUD }}
        request={RESEARCH_REQUEST}
        research={{ status: 'ready', data: completed }}
        onRequestChange={vi.fn()}
        onApproveCandidate={approve}
        onManualUpload={manual}
      />,
    )

    expect(screen.getByText('vendor:restricted-driver')).toBeVisible()
    expect(screen.getByText('Vendor entitlement required')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Approve immutable candidate' }))
    await user.click(screen.getByRole('button', { name: 'Use vendor upload path' }))
    expect(approve).toHaveBeenCalledWith(completed.result?.candidates[0])
    expect(manual).toHaveBeenCalledWith(completed.result?.candidates[0])
  })
})

describe('CloudSettingsPage', () => {
  const setupRequest: CloudSetupRequest = {
    schemaVersion: WEB_SCHEMA_VERSION,
    projectId: 'operator-project',
    region: 'us-central1',
    datasetPrefix: 'migration',
  }

  it('renders the reviewed command and masks the non-secret receipt without any credential field', async () => {
    const user = userEvent.setup()
    const verify = vi.fn()
    render(
      <CloudSettingsPage
        connection={{ status: 'ready', data: VERIFIED_CLOUD }}
        setupRequest={setupRequest}
        setup={{ status: 'ready', data: {
          schemaVersion: WEB_SCHEMA_VERSION,
          setupId: 'setup-123',
          projectId: 'operator-project',
          region: 'us-central1',
          command: 'gcloud projects describe operator-project',
          commandDigest: 'sha256:command',
          expiresAt: '2026-08-27T11:00:00Z',
        } }}
        receipt="receipt-opaque-value"
        verification={{ status: 'empty' }}
        onSetupRequestChange={vi.fn()}
        onReceiptChange={vi.fn()}
        onVerify={verify}
      />,
    )

    expect(screen.getByText('gcloud projects describe operator-project')).toBeVisible()
    const receipt = screen.getByLabelText('Non-secret verification receipt')
    expect(receipt).toHaveAttribute('type', 'password')
    expect(screen.queryByLabelText(/service-account|access key|refresh token/i)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Verify setup' }))
    expect(verify).toHaveBeenCalledWith('setup-123', 'receipt-opaque-value')
  })

  it('shows incomplete verification capabilities without echoing the receipt', () => {
    render(
      <CloudSettingsPage
        connection={{ status: 'ready', data: VERIFIED_CLOUD }}
        setupRequest={setupRequest}
        setup={{ status: 'empty' }}
        receipt="receipt-must-not-appear-as-text"
        verification={{ status: 'ready', data: {
          schemaVersion: WEB_SCHEMA_VERSION,
          setupId: 'setup-123',
          status: 'incomplete',
          projectId: 'operator-project',
          region: 'us-central1',
          verifiedAt: '2026-08-27T10:00:00Z',
          missingCapabilities: ['artifactregistry.repositories.downloadArtifacts'],
        } }}
        onSetupRequestChange={vi.fn()}
        onReceiptChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Setup incomplete')).toBeVisible()
    expect(screen.getByText('artifactregistry.repositories.downloadArtifacts')).toBeVisible()
    expect(screen.queryByText('receipt-must-not-appear-as-text')).not.toBeInTheDocument()
  })
})

describe('SourceDetailPage', () => {
  it('renders the contract-backed three-pane source, plan, and evidence view', async () => {
    const user = userEvent.setup()
    const selectPane = vi.fn()
    const copy = vi.fn()
    render(
      <SourceDetailPage
        source={{ status: 'ready', data: LIVE_SOURCE }}
        events={EVENTS}
        activePane="source"
        onActivePaneChange={selectPane}
        onCopy={copy}
      />,
    )

    expect(screen.getByRole('heading', { name: 'Source system / Google VM' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Agentic compiler middleware' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Google BigQuery' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Source system / Google VM mirror' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Agentic compiler middleware mirror' })).toBeVisible()
    expect(screen.getByRole('region', { name: 'Google BigQuery mirror' })).toBeVisible()
    expect(screen.getByText('LIVE RUN NARRATION · EVENT 1')).toBeVisible()
    expect(screen.getByText('f1f2f3c4')).toBeVisible()
    expect(screen.getByText('packed_decimal')).toBeVisible()
    expect(screen.getAllByText('Source migration reconciled')).toHaveLength(2)
    expect(screen.getByText('sha256:destination')).toBeVisible()

    await user.click(screen.getByRole('tab', { name: 'Evidence & timeline' }))
    expect(selectPane).toHaveBeenCalledWith('evidence')
    screen.getByRole('tab', { name: 'Source & schema' }).focus()
    await user.keyboard('{ArrowRight}')
    expect(selectPane).toHaveBeenCalledWith('plan')
    await user.click(screen.getByRole('button', { name: 'Copy raw hex' }))
    expect(copy).toHaveBeenCalledWith('f1f2f3c4')
  })

  it('shows all three truthful progress panes without fabricating missing captured artifacts', () => {
    const progressOnly: LiveSourceResponse = { ...LIVE_SOURCE, detail: undefined }
    render(
      <SourceDetailPage
        source={{ status: 'ready', data: progressOnly, stale: true, connection: 'offline' }}
        activePane="source"
        onActivePaneChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Live updates are offline')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Source system / Google VM' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Agentic compiler middleware' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Google BigQuery' })).toBeVisible()
    expect(screen.getByText('sha256:plan')).toBeVisible()
    expect(screen.getByText('Schema and sample artifacts have not been captured for this run. The authenticated counters remain visible.')).toBeVisible()
    expect(screen.queryByText('Address number')).not.toBeInTheDocument()
  })

  it('filters timeline events to the selected source and portfolio-wide events', () => {
    const events: readonly LiveRunEvent[] = [
      ...EVENTS,
      { ...EVENTS[0], eventId: 'event-maxdb', sourceId: 'maxdb', summary: 'MaxDB-only event' },
      { ...EVENTS[0], eventId: 'event-portfolio', sourceId: undefined, summary: 'Portfolio event' },
    ]
    render(
      <SourceDetailPage
        source={{ status: 'ready', data: LIVE_SOURCE }}
        events={events}
        activePane="evidence"
        onActivePaneChange={vi.fn()}
      />,
    )

    const evidencePanel = screen.getByRole('tabpanel', { name: 'Evidence & timeline' })
    expect(within(evidencePanel).getByText('Source migration reconciled')).toBeVisible()
    expect(within(evidencePanel).getByText('Portfolio event')).toBeVisible()
    expect(within(evidencePanel).queryByText('MaxDB-only event')).not.toBeInTheDocument()
  })
})
