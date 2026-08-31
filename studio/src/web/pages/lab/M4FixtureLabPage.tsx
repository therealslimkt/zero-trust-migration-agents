import { useEffect, useState } from "react";

import { BrandBolt, PixelIcon, TerminalWindow } from "../../shared/ui";
import fixtureData from "./m4FixtureData.json";
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

export const M4_FIXTURE_SUMMARIES: readonly M4FixtureSummary[] = fixtureData.map((packet) => {
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
      if (!response.ok || !isRunnerResponse(body)) throw new Error("local_agent_unavailable");
      setState(body);
    } catch {
      setState({ status: "failed", code: "local_agent_unavailable" });
    }
  };
  const evidence = state.evidence;
  return <section className="m4-lab__runner" aria-labelledby="local-runner-title">
    <div>
      <p className="m4-lab__runner-eyebrow">LOOPBACK RUNNER AGENT</p>
      <h2 id="local-runner-title">Run the three synthetic cartridges for real.</h2>
      <p>This local-only action asks a sealed agent to run the fixed Docker evidence command. It has no cloud endpoint, no source credentials, and accepts no browser-supplied command or image.</p>
    </div>
    <div className="m4-lab__runner-action">
      <button type="button" className="m4-lab__runner-button" onClick={() => void start()} disabled={state.status === "running"}>
        <PixelIcon name="play" size="xs" color="white" />
        {state.status === "running" ? "Running cartridges…" : "Run local evidence"}
      </button>
      <p className={`m4-lab__runner-status m4-lab__runner-status--${state.status}`} aria-live="polite">
        {state.status === "idle" ? "Ready: Docker Desktop stays local." : null}
        {state.status === "running" ? "Agent is building, waiting for source health, and certifying counts." : null}
        {state.status === "failed" ? `Runner did not complete (${state.code ?? "unknown"}).` : null}
        {state.status === "succeeded" ? "Evidence complete: count-only result returned." : null}
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
          <p className="m4-lab__eyebrow">KERAUN / LOCAL CARTRIDGE LAB</p>
          <h1 id="m4-lab-title">Explore three migration recipes, safely.</h1>
          <p>Each cartridge turns one legacy source pattern into a deterministic migration recipe. Pick a system to inspect synthetic inputs, expected outputs, and the checks that must pass before a live connection.</p>
        </div>
        <span className="m4-lab__badge"><BrandBolt /><span>LOCAL FIXTURE LAB</span></span>
      </header>

      <section className="m4-lab__truth" aria-label="What this local lab proves">
        <span className="m4-lab__truth-icon"><BrandBolt /></span>
        <div><strong>What you can explore here</strong><p>Three checked-in synthetic migration recipes and their deterministic evidence. No sign-in is required to inspect this read-only lab; no live source, customer data, cloud job, hosted backend, or production plugin is represented.</p></div>
      </section>

      <section className="m4-lab__guide" aria-label="How to use this lab">
        <span><b>01</b>Choose a legacy system</span><span><b>02</b>Read its identity and output evidence</span><span><b>03</b>Inspect the checks that keep it honest</span>
      </section>

      <LocalCartridgeRunner />

      <div className="m4-lab__tabs" role="tablist" aria-label="Fixture cartridges">
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
            <small>{fixture.fixtureStatus === "validated_fixture" ? "validated local packet" : "packet integration pending"}</small>
          </button>
        ))}
      </div>

      <section className="m4-lab__grid" aria-label={`${selected.title} local fixture evidence`}>
        <TerminalWindow title={`${selected.title} fixture packet`} breadcrumb={`lab/m4/${selected.cartridgeId}`} accent="google-blue" variant="glass" scanlines cornerBrackets>
          <dl className="m4-lab__facts">
            <div><dt>Legacy source</dt><dd>{selected.legacy}</dd></div>
            <div><dt>Identity boundary</dt><dd>{selected.identity}</dd></div>
            <div><dt>Readiness</dt><dd>{validated ? "synthetic_fixture / validated" : "synthetic_fixture / awaiting packet"}</dd></div>
            <div><dt>Packet digest</dt><dd>{digest(selected.packetDigest)}</dd></div>
            <div><dt>Transform spec digest</dt><dd>{digest(selected.transformSpecDigest)}</dd></div>
            <div><dt>Reconciliation digest</dt><dd>{digest(selected.reconciliationDigest)}</dd></div>
          </dl>
        </TerminalWindow>

        <TerminalWindow title="Deterministic checks" breadcrumb="lab/m4/checks" accent="google-yellow" variant="elevated" scanlines>
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

      <footer className="m4-lab__footer">
        <span>Evidence surface: canonical local fixture packet + deterministic reconciliation</span>
        <a href="/">Return to overview</a>
      </footer>
    </main>
  );
}
