import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LocalCartridgeRunner, M4FixtureLabPage } from './M4FixtureLabPage'

describe('M4FixtureLabPage', () => {
  it('positions three synthetic cartridges as preloaded plugin candidates without cloud-success claims', () => {
    render(<M4FixtureLabPage />)
    expect(screen.getByText('PRELOADED DEMOS')).toBeInTheDocument()
    expect(screen.getByText('JD Edwards EnterpriseOne')).toBeInTheDocument()
    expect(screen.getByText('Microsoft Dynamics AX')).toBeInTheDocument()
    expect(screen.getByText('Oracle EBS on Oracle 19c')).toBeInTheDocument()
    expect(screen.getByText(/No customer data, live source, Apache Beam job, or BigQuery write occurs on this page/)).toBeInTheDocument()
    expect(screen.getByText('Discover or research a cartridge')).toBeInTheDocument()
    expect(screen.getByText('Download the portable plugin')).toBeInTheDocument()
  })

  it('switches only preloaded synthetic contract evidence', () => {
    render(<M4FixtureLabPage />)
    fireEvent.click(screen.getByRole('tab', { name: /Microsoft Dynamics AX/i }))
    expect(screen.getByText('company + partition + table + RecId')).toBeInTheDocument()
    expect(screen.getByText('synthetic_contract / verified')).toBeInTheDocument()
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Snapshot 6')
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Expected silver 6')
  })

  it('labels the local runner as a real loopback-only action when enabled', () => {
    render(<LocalCartridgeRunner enabled />)
    expect(screen.getByRole('button', { name: 'Verify local evidence' })).toBeInTheDocument()
    expect(screen.getByText(/sealed agent to run the fixed Docker evidence command/i)).toBeInTheDocument()
    expect(screen.getByText(/no cloud endpoint, source credentials, or browser-supplied command/i)).toBeInTheDocument()
  })
})
