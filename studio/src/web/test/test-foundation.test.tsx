import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

function FoundationProbe() {
  const [expanded, setExpanded] = useState(false)

  return (
    <section aria-labelledby="foundation-heading">
      <h1 id="foundation-heading">Migration detail</h1>
      <button type="button" aria-expanded={expanded} onClick={() => setExpanded((current) => !current)}>
        Toggle evidence
      </button>
      {expanded ? <p role="status">Evidence visible</p> : null}
    </section>
  )
}

describe('web test foundation', () => {
  it('supports accessible interaction tests', async () => {
    const user = userEvent.setup()
    render(<FoundationProbe />)

    const toggle = screen.getByRole('button', { name: 'Toggle evidence' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('status')).toHaveTextContent('Evidence visible')
  })

  it('provides deterministic browser observers for motion and layout components', () => {
    expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(false)
    expect(new ResizeObserver(() => undefined)).toBeInstanceOf(ResizeObserver)
    expect(new IntersectionObserver(() => undefined)).toBeInstanceOf(IntersectionObserver)
  })
})
