// Browser-side client for the loopback stage executor. The dev server holds the
// executor credential and injects it; nothing secret is compiled in here.

export type StageQuery = { readonly title: string; readonly sql: string }
export type StageCartridge = {
  readonly id: string
  readonly label: string
  readonly service: string
  readonly queries: readonly StageQuery[]
}
export type StageRows = {
  readonly columns: readonly string[]
  readonly rows: readonly (readonly string[])[]
  readonly rowCount: number
  readonly jobId?: string
}
export type LoadResult = StageCartridge & { readonly database: string; readonly user: string }
export type QuarantineRow = {
  readonly aban8: number
  readonly reason: string
  readonly detail: string
  readonly recordLength: number
  readonly comp3FieldHex: string
  readonly sourceTable: string
  readonly sourceKey: string
}
export type CompileResult = {
  readonly records: number
  readonly read: number
  readonly rejected: number
  readonly beamVersion: string
  readonly table: string
  readonly quarantine: readonly QuarantineRow[]
  readonly mapping: readonly { readonly column: string; readonly dataClass: string }[]
}
export type QuarantineManifest = {
  readonly cartridge: string
  readonly count: number
  readonly columns: readonly string[]
  readonly rows: readonly QuarantineRow[]
  readonly csv: string
  readonly filename: string
}
export type LandResult = {
  readonly table: string
  readonly jobId: string
  readonly rowsRead: number
  readonly rowsWritten: number
  readonly matched: boolean
  readonly queries: readonly string[]
}

const MESSAGES: Record<string, string> = {
  select_only: 'Only a SELECT statement is accepted here.',
  read_only_only: 'That statement writes or changes schema; this surface is read-only.',
  single_statement_only: 'Send one statement at a time.',
  query_length: 'The query is empty or too long.',
  unknown_cartridge: 'That cartridge is not loaded.',
  stage_timeout: 'The stage did not finish in time.',
  stage_failed: 'The stage failed and reported nothing further.',
  command_failed: 'The sealed lab refused the command.',
}

export class StageError extends Error {
  readonly code: string

  constructor(code: string) {
    super(MESSAGES[code] ?? code)
    this.code = code
  }
}

async function post<T>(stage: string, body: Record<string, unknown>): Promise<T> {
  const response = await fetch(`/api/stages/v1/stages/${stage}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store',
    body: JSON.stringify(body),
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new StageError(payload?.code ?? 'stage_failed')
  return payload as T
}

export const stages = {
  list: async (): Promise<readonly StageCartridge[]> => {
    const response = await fetch('/api/stages/v1/stages', { cache: 'no-store' })
    if (!response.ok) throw new StageError('stage_failed')
    return (await response.json()).cartridges
  },
  load: (cartridge: string) => post<LoadResult>('load', { cartridge }),
  source: (cartridge: string, sql: string) => post<StageRows>('source', { cartridge, sql }),
  compile: (cartridge: string) => post<CompileResult>('compile', { cartridge }),
  land: (cartridge: string) => post<LandResult>('land', { cartridge }),
  bq: (cartridge: string, sql: string) => post<StageRows>('bq', { cartridge, sql }),
  quarantine: (cartridge: string) => post<QuarantineManifest>('quarantine', { cartridge }),
}
