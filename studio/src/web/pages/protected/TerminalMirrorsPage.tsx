import '../public/public-pages.css'
import { useState } from 'react'

// Three synchronized stage mirrors for ONE migration:
//   private source VM  →  agentic compiler + Beam  →  BigQuery
// Frames below are the recorded output of
// `scripts/demo_cluster_to_bigquery.py --load` against ztm-agent-9049c3.

const SOURCE_FRAMES = [
  '$ connect legacy source (sealed, internal-only, no egress)',
  'host        legacy-jde-db',
  'export      clustered binary · 386 bytes',
  'readable?   NO — every record separately zlib-compressed',
  '',
  '00000000  4d 58 44 42 4b 4e 41 31  |MXDBKNA1|',
  '00000010  52 00 00 00 d2 c7 dc f0  |R.......|',
  '00000020  0b 52 b2 52 32 80 01 43  |.R.R2..C|',
  '00000030  a0 60 68 30 90 e3 e7 e8  |.`h0....|',
  '',
  'a warehouse loader pointed here gets ONE opaque BYTES column',
  'sha256      6698000415f25413fd88032ae4775ebb…',
]

const COMPILER_FRAMES = [
  '$ agentic compiler — declarative contract only',
  'planner     gemini-3.5-flash on Vertex AI (us)',
  'authority   may choose rename · cast · drop',
  'authority   may NOT emit or execute code',
  '',
  'adapter     MXDBKNA1 magic + version  ......  OK',
  'adapter     record length + CRC32 verified BEFORE decompress',
  'bounds      <=10,000 records · <=16 KiB uncompressed each',
  'schema      keys outside {KUNNR,NAME1,ORT01,LAND1} rejected',
  'failure     malformed input -> NO partial output',
  '',
  'KUNNR  -> customer_number  STRING  [financialAccount]',
  'NAME1  -> name             STRING  [name]',
  'ORT01  -> city             STRING  [address]',
  'LAND1  -> country          STRING  [public]',
  '',
  'digest      bound; awaiting one human approval',
  'approved    executing pre-registered typed transform',
]

const BQ_FRAMES = [
  '$ load into BigQuery — explicit schema, never autodetect',
  'project     ztm-agent-9049c3',
  'table       keraun_demo.sap_kna1_clustered',
  'job         ce235d05-810e-4457-b134-76dc9dfa4717',
  '',
  'customer_number  name                          city     country',
  '0000000001       Northstar Components LLC      Chicago  US',
  '0000000002       Blue Heron Manufacturing Ltd  Toronto  CA',
  '0000000003       Juniper Industrial GmbH       Berlin   DE',
  '0000000004       Copper Finch Systems KK       Tokyo    JP',
  '',
  'RECONCILE   4 decoded = 4 loaded          OK',
  'audit row   written with lineage + digests',
]

type StageId = 'source' | 'compiler' | 'bigquery'
const STAGES: readonly { id: StageId; title: string; host: string; frames: string[] }[] = [
  { id: 'source', title: '01 · PRIVATE SOURCE VM', host: 'legacy-jde-db', frames: SOURCE_FRAMES },
  { id: 'compiler', title: '02 · AGENTIC COMPILER + BEAM', host: 'vertex · gemini-3.5-flash', frames: COMPILER_FRAMES },
  { id: 'bigquery', title: '03 · BIGQUERY', host: 'keraun_demo', frames: BQ_FRAMES },
]

export function TerminalMirrorsPage() {
  const [out, setOut] = useState<Record<StageId, string[]>>({ source: [], compiler: [], bigquery: [] })
  const [active, setActive] = useState<StageId | null>(null)
  const [done, setDone] = useState<Record<StageId, boolean>>({ source: false, compiler: false, bigquery: false })
  const [running, setRunning] = useState(false)

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

  const run = async () => {
    setRunning(true)
    setOut({ source: [], compiler: [], bigquery: [] })
    setDone({ source: false, compiler: false, bigquery: false })
    for (const stage of STAGES) {
      setActive(stage.id)
      for (const line of stage.frames) {
        setOut((prev) => ({ ...prev, [stage.id]: [...prev[stage.id], line] }))
        await sleep(line === '' ? 60 : 130)
      }
      setDone((prev) => ({ ...prev, [stage.id]: true }))
      await sleep(280)
    }
    setActive(null)
    setRunning(false)
  }

  return (
    <main className="mirrors">
      <header className="mirrors__head">
        <div>
          <span className="mirrors__eyebrow">ONE MIGRATION · THREE SYNCHRONIZED MIRRORS</span>
          <h1>Clustered binary → typed BigQuery columns</h1>
          <p>
            Problem data never leaves the private perimeter in raw form. The compiler emits a
            declarative contract — never code — and only the approved, pre-registered transform writes.
          </p>
        </div>
        <button type="button" className="mirrors__play" onClick={() => void run()} disabled={running}>
          {running ? 'RUNNING…' : '▶  RUN JDE MIGRATION'}
        </button>
      </header>
      <div className="mirrors__grid">
        {STAGES.map((stage) => (
          <section key={stage.id} className={`mirror${done[stage.id] ? ' mirror--done' : ''}${active === stage.id ? ' mirror--active' : ''}`}>
            <header className="mirror__bar">
              <span className="mirror__dots"><i /><i /><i /></span>
              <span className="mirror__title">{stage.title}</span>
              <span className="mirror__host">{stage.host}</span>
            </header>
            <pre className="mirror__body">
              {out[stage.id].length === 0 ? '$ idle — press RUN JDE MIGRATION' : out[stage.id].join('\n')}
            </pre>
            <footer className="mirror__foot">
              {done[stage.id] ? 'STAGE COMPLETE · SANITIZED FRAMES ONLY' : active === stage.id ? 'STREAMING…' : 'READ-ONLY MIRROR'}
            </footer>
          </section>
        ))}
      </div>
      <p className="mirrors__prov">
        Frames are the recorded output of <code>scripts/demo_cluster_to_bigquery.py --load</code> against
        project <b>ztm-agent-9049c3</b> — BigQuery job <b>ce235d05-810e-4457-b134-76dc9dfa4717</b>, 4 decoded = 4 loaded.
        Fixture data is synthetic and deidentified.
      </p>
    </main>
  )
}
