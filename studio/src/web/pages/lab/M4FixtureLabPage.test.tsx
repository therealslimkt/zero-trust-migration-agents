import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { M4FixtureLabPage } from './M4FixtureLabPage'

describe('M4FixtureLabPage', () => {
  it('shows three local synthetic cartridges without cloud-success claims', () => {
    render(<M4FixtureLabPage />)
    expect(screen.getByText('LOCAL SYNTHETIC FIXTURE')).toBeInTheDocument()
    expect(screen.getByText('JD Edwards EnterpriseOne')).toBeInTheDocument()
    expect(screen.getByText('Microsoft Dynamics AX')).toBeInTheDocument()
    expect(screen.getByText('Oracle EBS on Oracle 19c')).toBeInTheDocument()
    expect(screen.getByText(/No Dataflow job, BigQuery table/)).toBeInTheDocument()
  })

  it('switches only local fixture evidence', () => {
    render(<M4FixtureLabPage />)
    fireEvent.click(screen.getByRole('tab', { name: /Microsoft Dynamics AX/i }))
    expect(screen.getByText('company + partition + table + RecId')).toBeInTheDocument()
    expect(screen.getByText('synthetic_fixture / validated')).toBeInTheDocument()
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Snapshot 6')
    expect(screen.getByLabelText('Packet record counts')).toHaveTextContent('Expected silver 6')
  })
})
