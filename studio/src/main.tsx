import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource-variable/geist-mono'
import './index.css'
import { WebApplication } from './web/WebApplication.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <WebApplication />
  </StrictMode>,
)
