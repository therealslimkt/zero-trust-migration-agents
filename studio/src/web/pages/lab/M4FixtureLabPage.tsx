import { useEffect, useState } from "react";

import { BrandBolt, PixelIcon, TerminalWindow } from "../../shared/ui";
import fixtureData from "./m4FixtureData.json";
import { PixelPortrait, type PortraitId } from "./PixelPortrait";
import "./m4-fixture-lab.css";

export interface M4FixtureSummary {
  readonly cartridgeId: "jde" | "dynamics_ax" | "oracle_ebs_19c";
  readonly title: string;
  readonly legacy: string;
  readonly identity: string;
  readonly fixtureStatus: "pending_packet" | "validated_fixture";
  readonly packetDigest?: string;
  readonly transformSpecDigest?: string;
  readonly reconciliationDigest?: string;
  readonly snapshotRecords?: number;
  readonly silverRecords?: number;
  readonly invalidRecords?: number;
  readonly checks: readonly string[];
}

const FIXTURE_DETAILS = {
  jde: {
    title: "JD Edwards EnterpriseOne",
    legacy: "IBM i / F0911 journal fixture",
    identity: "company + document type + number + line + ledger",
    checks: ["UPMJ zero/leap/invalid", "ordered insert/update/delete journal", "bronze + silver reconciliation"],
  },
  dynamics_ax: {
    title: "Microsoft Dynamics AX",
    legacy: "SQL Server application metadata fixture",
    identity: "company + partition + table + RecId",
    checks: ["base/derived metadata", "watermark delta", "orphan and duplicate rejection"],
  },
  oracle_ebs_19c: {
    title: "Oracle EBS on Oracle 19c",
    legacy: "E-Business Suite flexfield fixture",
    identity: "application + table + context + segment + metadata version",
    checks: ["FND descriptive flexfields", "LAST_UPDATE_DATE delta", "ambiguous context rejection"],
  },
} as const;

const M4_FIXTURE_SUMMARIES: readonly M4FixtureSummary[] = fixtureData.map((packet) => {
  const cartridgeId = packet.cartridgeId as M4FixtureSummary["cartridgeId"];
  const detail = FIXTURE_DETAILS[cartridgeId];
  return { ...packet, cartridgeId, ...detail, fixtureStatus: "validated_fixture" };
});

function digest(value?: string) {
  return value ? <code>{value}</code> : <span className="m4-lab__pending-value">Awaiting local packet join</span>;
}

type LocalRunnerStatus = "idle" | "running" | "succeeded" | "failed";

interface LocalEvidence {
  readonly schemaVersion: "keraun.cartridge-evidence/v1";
  readonly synthetic: true;
  readonly checks: Readonly<Record<"jdeInvalidCyyddd" | "axOrphanDerived" | "ebsUnmappedFlexfield", number>>;
}

interface LocalRunnerResponse {
  readonly status: LocalRunnerStatus;
  readonly requestId?: string;
  readonly evidence?: LocalEvidence;
  readonly code?: string;
}

const BAD_GUYS: ReadonlyArray<{
  cartridgeId: string;
  alias: string;
  portrait: PortraitId;
  source: string;
  crime: string;
  tell: string;
  team: ReadonlyArray<{ id: PortraitId; name: string; role: string }>;
}> = [
  {
    cartridgeId: "jde",
    alias: "DAY ZERO",
    portrait: "day-zero",
    source: "JD Edwards EnterpriseOne 9.2 / IBM i",
    crime: "Dates that are not dates.",
    tell: "CYYDDD julian integers — 124001 is not January 24th, and 100000 is not a date at all.",
    team: [
      { id: "analyst", name: "source_analyst_jde", role: "frozen single-turn profiler" },
      { id: "prisma", name: "PRISMA", role: "compiles the declarative cast" },
      { id: "vale", name: "VALE", role: "rejects any lossy narrowing" },
    ],
  },
  {
    cartridgeId: "dynamics_ax",
    alias: "THE HEIR",
    portrait: "the-heir",
    source: "Microsoft Dynamics AX 2012 R3 / SQL Server",
    crime: "Children of parents that no longer exist.",
    tell: "64-bit RecId table inheritance — a derived row whose base row is gone still looks valid.",
    team: [
      { id: "analyst", name: "source_analyst_ax", role: "resolves the inheritance chain" },
      { id: "vale", name: "VALE", role: "fails closed on orphan-derived rows" },
      { id: "ledger", name: "LEDGER", role: "reconciles accepted vs rejected" },
    ],
  },
  {
    cartridgeId: "oracle_ebs_19c",
    alias: "ALIAS",
    portrait: "alias",
    source: "Oracle E-Business Suite / Oracle 19c",
    crime: "Real columns wearing a disguise.",
    tell: "ATTRIBUTE1..15 descriptive flexfields whose meaning lives in a separate FND catalog.",
    team: [
      { id: "analyst", name: "source_analyst_oracle", role: "reads FND flexfield context" },
      { id: "prisma", name: "PRISMA", role: "emits typed output columns" },
      { id: "atlas", name: "ATLAS", role: "coordinates, never approves" },
    ],
  },
];

const LOCAL_AGENT_ENABLED = import.meta.env.DEV && import.meta.env.VITE_LOCAL_CARTRIDGE_AGENT === "true";

function isRunnerResponse(value: unknown): value is LocalRunnerResponse {
  return Boolean(value && typeof value === "object" && "status" in value && ["idle", "running", "succeeded", "failed"].includes(String(value.status)));
}

export function LocalCartridgeRunner({ enabled = LOCAL_AGENT_ENABLED }: { readonly enabled?: boolean }) {
  const [state, setState] = useState<LocalRunnerResponse>({ status: "idle" });

  useEffect(() => {
    if (!enabled || state.status !== "running") return undefined;
    const timer = window.setInterval(() => {
      void fetch("/api/local-cartridge/v1/evidence-runs/current", { cache: "no-store" })
        .then(async (response) => response.ok ? response.json() : Promise.reject(new Error("local_agent_unavailable")))
        .then((response: unknown) => { if (isRunnerResponse(response)) setState(response); })
        .catch(() => setState({ status: "failed", code: "local_agent_unavailable" }));
    }, 750);
    return () => window.clearInterval(timer);
  }, [enabled, state.status]);

  if (!enabled) return null;
  const start = async () => {
    setState({ status: "running" });
    try {
      const response = await fetch("/api/local-cartridge/v1/evidence-runs", { method: "POST", cache: "no-store" });
      const body: unknown = await response.json();
      if ((!response.ok && response.status !== 409) || !isRunnerResponse(body)) throw new Error("local_agent_unavailable");
      setState(body);
    } catch {
      setState({ status: "failed", code: "local_agent_unavailable" });
    }
  };
  const evidence = state.evidence;
  return <section className="m4-lab__runner" aria-labelledby="local-runner-title">
    <div>
      <p className="m4-lab__runner-eyebrow">SEALED SANDBOX PREFLIGHT</p>
      <h2 id="local-runner-title">Verify the preloaded three-cartridge portfolio.</h2>
      <p>This local-only gate asks a sealed agent to run the fixed Docker evidence command. It has no cloud endpoint, source credentials, or browser-supplied command or image. A pass certifies the synthetic fixture boundary before a candidate is promoted into Mission Control.</p>
    </div>
    <div className="m4-lab__runner-action">
      <button type="button" className="m4-lab__runner-button" onClick={() => void start()} disabled={state.status === "running"}>
        <PixelIcon name="play" size="xs" color="white" />
        {state.status === "running" ? "Verifying cartridges…" : "Verify local evidence"}
      </button>
      <p className={`m4-lab__runner-status m4-lab__runner-status--${state.status}`} aria-live="polite">
        {state.status === "idle" ? "Ready: Docker Desktop stays local; no migration is launched." : null}
        {state.status === "running" ? "Agent is building, waiting for source health, and certifying count-only guardrails." : null}
        {state.status === "failed" ? `Runner did not complete (${state.code ?? "unknown"}).` : null}
        {state.status === "succeeded" ? "Preflight passed: this is not yet Beam or BigQuery execution proof." : null}
      </p>
    </div>
    {evidence ? <pre className="m4-lab__runner-result">{JSON.stringify(evidence, null, 2)}</pre> : null}
  </section>;
}

export function M4FixtureLabPage() {
  const [selectedId, setSelectedId] = useState<M4FixtureSummary["cartridgeId"]>("jde");
  const selected = M4_FIXTURE_SUMMARIES.find((fixture) => fixture.cartridgeId === selectedId) ?? M4_FIXTURE_SUMMARIES[0];
  const validated = selected.fixtureStatus === "validated_fixture";

  return (
    <main className="m4-lab" aria-labelledby="m4-lab-title">
      <header className="m4-lab__header">
        <div>
          <p className="m4-lab__eyebrow">KERAUN / OPEN PLUGIN FACTORY</p>
          <h1 id="m4-lab-title">Turn a sticky source into a portable migration agent.</h1>
          <p>Start with a vetted cartridge or ask the research fleet to discover one. The three preloaded examples show the deterministic source contracts, translation rules, and evidence gates that a candidate must satisfy before Mission Control can authorize a migration test.</p>
        </div>
        <span className="m4-lab__badge"><BrandBolt /><span>PRELOADED DEMOS</span></span>
      </header>

      <section className="m4-lab__truth" aria-label="What this preflight proves">
        <span className="m4-lab__truth-icon"><BrandBolt /></span>
        <div><strong>This is a plugin verification gate—not a second product.</strong><p>These are synthetic source emulators and deterministic evidence packets for three preloaded demo cartridges. No customer data, live source, Apache Beam job, or BigQuery write occurs on this page. Passing the gate produces a candidate for the authenticated Mission Control run, where its sandbox, compiler, and warehouse evidence must be reviewed.</p></div>
      </section>

      <section className="m4-lab__guide" aria-label="Plugin factory lifecycle">
        <span><b>01</b>Discover or research a cartridge</span><span><b>02</b>Verify its source contract</span><span><b>03</b>Review a sealed Mission Control run</span><span><b>04</b>Download the portable plugin</span>
      </section>

      <LocalCartridgeRunner />

      <div className="m4-lab__tabs" role="tablist" aria-label="Preloaded demo cartridges">
        {M4_FIXTURE_SUMMARIES.map((fixture) => (
          <button
            key={fixture.cartridgeId}
            type="button"
            role="tab"
            aria-selected={selected.cartridgeId === fixture.cartridgeId}
            className={selected.cartridgeId === fixture.cartridgeId ? "m4-lab__tab m4-lab__tab--active" : "m4-lab__tab"}
            onClick={() => setSelectedId(fixture.cartridgeId)}
          >
            <span>{fixture.title}</span>
            <small>{fixture.fixtureStatus === "validated_fixture" ? "verified synthetic contract" : "packet integration pending"}</small>
          </button>
        ))}
      </div>

      <section className="m4-lab__grid" aria-label={`${selected.title} preloaded cartridge evidence`}>
        <TerminalWindow title={`${selected.title} source contract`} breadcrumb={`factory/preloaded/${selected.cartridgeId}`} accent="google-blue" variant="glass" scanlines cornerBrackets>
          <dl className="m4-lab__facts">
            <div><dt>Legacy source</dt><dd>{selected.legacy}</dd></div>
            <div><dt>Identity boundary</dt><dd>{selected.identity}</dd></div>
            <div><dt>Readiness</dt><dd>{validated ? "synthetic_contract / verified" : "synthetic_contract / awaiting packet"}</dd></div>
            <div><dt>Packet digest</dt><dd>{digest(selected.packetDigest)}</dd></div>
            <div><dt>Transform spec digest</dt><dd>{digest(selected.transformSpecDigest)}</dd></div>
            <div><dt>Reconciliation digest</dt><dd>{digest(selected.reconciliationDigest)}</dd></div>
          </dl>
        </TerminalWindow>

        <TerminalWindow title="Deterministic gates" breadcrumb="factory/preflight/gates" accent="google-yellow" variant="elevated" scanlines>
          <ul className="m4-lab__checks">
            {selected.checks.map((check) => <li key={check}><PixelIcon name="check-pixel" size="xs" color="google-green" />{check}</li>)}
          </ul>
          <div className="m4-lab__counts" aria-label="Packet record counts">
            <span>Snapshot <strong>{selected.snapshotRecords ?? "—"}</strong></span>
            <span>Expected silver <strong>{selected.silverRecords ?? "—"}</strong></span>
            <span>Invalid rejected <strong>{selected.invalidRecords ?? "—"}</strong></span>
          </div>
        </TerminalWindow>
      </section>

      <section className="m4-lab__badguys" aria-label="The three legacy adversaries">
        <header className="m4-lab__badguys-head">
          <h2>The three bad guys</h2>
          <p>Each preloaded cartridge exists to defeat one specific, well-documented legacy data pathology. The fleet assigns a least-authority team per adversary.</p>
        </header>
        <div className="m4-lab__badguys-grid">
          {BAD_GUYS.map((v) => (
            <article
              key={v.cartridgeId}
              className={selected.cartridgeId === v.cartridgeId ? "m4-lab__villain m4-lab__villain--active" : "m4-lab__villain"}
            >
              <div className="m4-lab__villain-top">
                <PixelPortrait id={v.portrait} size={104} title={v.alias} />
                <div>
                  <h3>{v.alias}</h3>
                  <p className="m4-lab__villain-src">{v.source}</p>
                </div>
              </div>
              <p className="m4-lab__villain-crime">{v.crime}</p>
              <p className="m4-lab__villain-tell">{v.tell}</p>
              <ul className="m4-lab__team" aria-label={`Fleet team assigned to ${v.alias}`}>
                {v.team.map((a) => (
                  <li key={`${v.cartridgeId}-${a.name}`}>
                    <PixelPortrait id={a.id} size={40} title={a.name} />
                    <span><b>{a.name}</b>{a.role}</span>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <footer className="m4-lab__footer">
        <span>Candidate stage: synthetic source contract + deterministic reconciliation. Mission Control, Beam, BigQuery, and plugin download remain separate auditable stages.</span>
        <a href="/">Return to overview</a>
      </footer>
    </main>
  );
}
