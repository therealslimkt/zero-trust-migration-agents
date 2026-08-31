import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LocalCartridgeRunner, M4FixtureLabPage } from './M4FixtureLabPage'

describe('M4FixtureLabPage', () => {
  it('shows three local synthetic cartridges without cloud-success claims', () => {
    render(<M4FixtureLabPage />)
    expect(screen.getByText('LOCAL FIXTURE LAB')).toBeInTheDocument()
    expect(screen.getByText('JD Edwards EnterpriseOne')).toBeInTheDocument()
    expect(screen.getByText('Microsoft Dynamics AX')).toBeInTheDocument()
    expect(screen.getByText('Oracle EBS on Oracle 19c')).toBeInTheDocument()
    expect(screen.getByText(/read-only lab; no live source, customer data, cloud job/)).toBeInTheDocument()
    expect(screen.getByText('Choose a legacy system')).toBeInTheDocument()
  })

  it('switches only local fixture evidence', () => {
    render(<M4FixtureLabPage />)
    fireEvent.click(screen.getByRole('tab', { name: /Microsoft Dynamics AX/i }))
    expect(screen.getByText('company + partition + table + RecId')).toBeInTheDocument()
    expect(screen.getByText('synthetic_fixture / validated')).toBeInTheDocument()
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Snapshot 6')
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Expected silver 6')
  })

  it('labels the local runner as a real loopback-only action when enabled', () => {
    render(<LocalCartridgeRunner enabled />)
    expect(screen.getByRole('button', { name: 'Run local evidence' })).toBeInTheDocument()
    expect(screen.getByText(/sealed agent to run the fixed Docker evidence command/i)).toBeInTheDocument()
    expect(screen.getByText(/no cloud endpoint, no source credentials/i)).toBeInTheDocument()
  })
})
