import type { MouseEvent } from "react";
import { ArchitectureDiagram } from "./ArchitectureDiagram";
import { PixelIcon, StatusBeacon, type PixelIconName, type ThemeMode } from "../../shared/ui/index";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
import "./public-pages.css";

export interface CreatorFact {
  readonly name: string;
  readonly role?: string;
  readonly affiliation?: string;
  readonly profileUrl?: string;
  readonly bio?: string;
}

export interface SubmissionFacts {
  readonly title?: string;
  readonly track?: string;
  readonly repositoryUrl?: string;
  readonly submittedAt?: string;
  readonly license?: string;
}

export interface AboutPageProps {
  onNavigate?: (route: string) => void;
  theme?: ThemeMode;
  onThemeChange?: (theme: ThemeMode) => void;
  creators?: readonly CreatorFact[];
  submissionFacts?: SubmissionFacts;
  authStatus?: SiteAuthStatus;
  userName?: string | null;
  userEmail?: string | null;
  userPhoto?: string | null;
  onSignInClick?: () => void;
  onSignOutClick?: () => void;
  demo?: PublishedDemoDescriptor;
  dashboardRoute?: string;
  loginRoute?: string;
  sourceRepoUrl?: string;
}

const architecturePrinciples = [
  ["Private context", "The surface distinguishes public information from configuration and execution information."],
  ["Explicit approval", "Approval state is displayed from the control plane rather than assumed by the interface."],
  ["Evidence first", "Plan and evidence references are represented as data that a connected run may provide."],
  ["Honest replay", "Public playback is labelled as an exact synthetic recorded replay only when an owner publishes its descriptor."],
] as const;

const architectureStages: ReadonlyArray<{
  readonly number: string;
  readonly title: string;
  readonly detail: string;
  readonly technologies: ReadonlyArray<{ readonly name: string; readonly icon: PixelIconName; readonly color: "google-blue" | "google-red" | "google-yellow" | "google-green" }>;
}> = [
  {
    number: "01", title: "Private source edge", detail: "Legacy bytes remain on the Google VM and cross the Tailscale private path only as governed records and evidence.",
    technologies: [
      { name: "Compute Engine", icon: "compute-engine", color: "google-blue" },
      { name: "Tailscale", icon: "tailscale", color: "google-blue" },
      { name: "IBM Db2 for i", icon: "db2", color: "google-blue" },
      { name: "SAP MaxDB", icon: "maxdb", color: "google-red" },
      { name: "Btrieve", icon: "btrieve", color: "google-green" },
    ],
  },
  {
    number: "02", title: "Agentic compiler", detail: "Local Gemma protects source context; Gemini on Vertex plans declarative transforms against exact driver provenance.",
    technologies: [
      { name: "JDBC / JAR", icon: "jdbc-jar", color: "google-red" },
      { name: "Gemma", icon: "gemma", color: "google-blue" },
      { name: "Gemini", icon: "gemini", color: "google-yellow" },
      { name: "Vertex AI", icon: "vertex-ai", color: "google-blue" },
      { name: "Artifact Registry", icon: "artifact-registry", color: "google-red" },
    ],
  },
  {
    number: "03", title: "Trusted execution", detail: "The approved plan becomes an Apache Beam pipeline; Dataflow executes only after the portfolio gate records a decision.",
    technologies: [
      { name: "Apache Beam", icon: "apache-beam", color: "google-yellow" },
      { name: "Dataflow", icon: "dataflow", color: "google-blue" },
      { name: "Cloud Run", icon: "cloud-run", color: "google-green" },
      { name: "Identity Platform", icon: "identity-platform", color: "google-blue" },
    ],
  },
  {
    number: "04", title: "Verified destination", detail: "BigQuery rows are presented only beside their reconciliation, job, table, and audit evidence from the exact run.",
    technologies: [
      { name: "BigQuery", icon: "bigquery", color: "google-blue" },
      { name: "Google Cloud", icon: "google-cloud", color: "google-green" },
      { name: "Approval", icon: "shield-check", color: "google-yellow" },
      { name: "Evidence", icon: "radar", color: "google-green" },
    ],
  },
];

type FleetColor = "google-blue" | "google-red" | "google-yellow" | "google-green";

const fleetAgents: ReadonlyArray<{
  readonly codename: string;
  readonly role: string;
  readonly icon: PixelIconName;
  readonly color: FleetColor;
  readonly status: "operational" | "hardening";
  readonly mission: string;
  readonly boundary: string;
}> = [
  { codename: "ATLAS", role: "Fleet marshal", icon: "branch", color: "google-blue", status: "operational", mission: "Routes typed work, resumes durable runs, and keeps every specialist inside the approved migration state machine.", boundary: "Go control plane · may delegate and cancel · may never approve its own plan" },
  { codename: "JETTY", role: "Privacy guardian", icon: "cpu", color: "google-green", status: "operational", mission: "Decodes and protects source context on the Jetson edge before governed metadata can leave the private path.", boundary: "Jetson Orin · local Gemma · deterministic redaction · raw PII stays local" },
  { codename: "RUNE", role: "JDE archivist", icon: "db2", color: "google-blue", status: "operational", mission: "Interprets IBM Db2 for i, EBCDIC, packed decimal, and source-specific extraction evidence.", boundary: "Read-only source adapter · emits records and provenance, never destination writes" },
  { codename: "MARA", role: "MaxDB cartographer", icon: "maxdb", color: "google-red", status: "operational", mission: "Maps SAP MaxDB schemas and preserves binary and character semantics through the compiler handoff.", boundary: "Read-only source adapter · schema and type evidence" },
  { codename: "BRIX", role: "Btrieve archaeologist", icon: "btrieve", color: "google-green", status: "operational", mission: "Reconstructs record layouts and indexing semantics from legacy Btrieve estates.", boundary: "Read-only source adapter · record-layout evidence" },
  { codename: "MAVEN", role: "Driver librarian", icon: "artifact-registry", color: "google-red", status: "operational", mission: "Researches, verifies, and immutably publishes exact driver artifacts for reproducible compilation.", boundary: "Async Go worker · Vertex research · Artifact Registry provenance" },
  { codename: "PRISMA", role: "Transform architect", icon: "gemini", color: "google-yellow", status: "operational", mission: "Uses Gemini to propose declarative mappings from protected metadata and exact driver capabilities.", boundary: "Plan-only authority · cannot approve, execute, or mutate source data" },
  { codename: "VALE", role: "Policy auditor", icon: "shield-check", color: "google-blue", status: "operational", mission: "Applies deterministic validation to plans, evidence references, and approval preconditions.", boundary: "Fail-closed policy checks · no generative override" },
  { codename: "STEWARD", role: "Human governor", icon: "identity-platform", color: "google-yellow", status: "operational", mission: "Reviews the sealed portfolio digest and makes the one decision agents are not allowed to make.", boundary: "Identity-bound HITL approval · exact digest · immutable decision evidence" },
  { codename: "FLOW + LEDGER", role: "Execution and reconciliation", icon: "dataflow", color: "google-green", status: "hardening", mission: "Turns an approved Beam plan into Dataflow work, then proves BigQuery rows against jobs, tables, and audit evidence.", boundary: "Execute only after approval · publish only after reconciliation" },
];

const enterpriseControls: ReadonlyArray<{
  readonly name: string;
  readonly icon: PixelIconName;
  readonly now: string;
  readonly next: string;
}> = [
  { name: "Agent Registry", icon: "artifact-registry", now: "Versioned specialist contracts and immutable driver artifacts", next: "Queryable catalog, capabilities, owners, and rollout policy" },
  { name: "Agent Runtime", icon: "cloud-run", now: "Durable Go orchestration with resumable typed commands", next: "Isolated workers, leases, quotas, and regional placement" },
  { name: "Memory Bank", icon: "database", now: "Atomic run snapshots and append-only evidence events", next: "Weeks-long scoped context with retention and sovereignty policy" },
  { name: "Agent Identity", icon: "identity-platform", now: "User identity and server-side credential boundaries", next: "Per-agent workload identity and least-privilege tool grants" },
  { name: "Agent Gateway", icon: "tailscale", now: "Private Tailscale path and authenticated control-plane APIs", next: "Central tool policy, egress controls, rate limits, and revocation" },
  { name: "Model Armor", icon: "shield-check", now: "Protected metadata, schema validation, and fail-closed gates", next: "Prompt and response inspection with explicit policy evidence" },
  { name: "Observability", icon: "radar", now: "Persisted events, exact terminal streams, and run evidence", next: "Fleet-wide OpenTelemetry traces, SLOs, and delegation views" },
];

/** Architecture narrative with owner-supplied creators and submission facts only. */
export function AboutPage({
  onNavigate,
  theme = "dark",
  onThemeChange,
  creators,
  submissionFacts: _submissionFacts,
  authStatus = "unconfigured",
  userName,
  userEmail,
  userPhoto,
  onSignInClick,
  onSignOutClick,
  demo,
  dashboardRoute,
  loginRoute = "/login",
  sourceRepoUrl,
}: AboutPageProps) {
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
  };

  void navigate;

  return (
    <div className="public-page">
      <SiteHeader activeRoute="/about" onNavigate={onNavigate} authStatus={authStatus} userName={userName} userEmail={userEmail} userPhoto={userPhoto} onSignInClick={onSignInClick} onSignOutClick={onSignOutClick} theme={theme} onThemeChange={onThemeChange} demo={demo} loginRoute={loginRoute} aboutRoute="/about" dashboardRoute={dashboardRoute} skipTargetId="about-content" />
      <main id="about-content" className="public-main" tabIndex={-1}>
        <div className="public-container about-page-section">
          <section className="about-hero-box" aria-labelledby="about-title">
            <StatusBeacon status="neutral" label="ARCHITECTURE OVERVIEW" mode="steady" size="xs" />
            <h1 id="about-title" className="about-hero-box__title">A visual story for governed migration</h1>
            <p className="about-hero-box__subtitle">This experience explains the application’s intended trust boundaries and makes clear which public details have actually been provided. It does not claim a connected cloud environment, execution result, or release state on its own.</p>
            <div className="about-tags-row"><span className="telemetry-tag"><PixelIcon name="sparkle" size="xs" color="google-yellow" /><span>GEMINI 3.7 FLASH</span></span><span className="telemetry-tag"><PixelIcon name="shield-check" size="xs" color="google-blue" /><span>OWNER-SUPPLIED STATE</span></span><span className="telemetry-tag"><PixelIcon name="rewind" size="xs" color="google-green" /><span>EXACT REPLAY WHEN PUBLISHED</span></span></div>
          </section>

          <section className="about-story-card about-system-map" aria-labelledby="system-map-heading">
            <div className="about-story-card__header"><PixelIcon name="branch" size="md" color="google-blue" glow /><div><span className="section-head__eyebrow">RUNTIME ARCHITECTURE</span><h2 id="system-map-heading" className="about-story-card__title">One governed path from private bytes to verified rows</h2></div></div>
            <div className="about-system-map__rail" aria-label="Migration technology architecture">
              {architectureStages.map((stage, index) => <div className="about-system-map__segment" key={stage.number}>
                <article className="about-system-stage">
                  <header><span>{stage.number}</span><h3>{stage.title}</h3></header>
                  <p>{stage.detail}</p>
                  <ul>{stage.technologies.map((technology) => <li key={technology.name}><span className={`about-tech-icon about-tech-icon--${technology.color}`}><PixelIcon name={technology.icon} size="sm" color={technology.color} /></span><span>{technology.name}</span></li>)}</ul>
                </article>
                {index < architectureStages.length - 1 ? <div className="about-system-map__connector" aria-hidden="true"><span /><PixelIcon name="play" size="xs" color="google-yellow" /></div> : null}
              </div>)}
            </div>
            <div className="about-trust-spine"><PixelIcon name="identity-platform" color="google-blue" /><strong>Identity-derived ownership</strong><span>→</span><PixelIcon name="shield-check" color="google-yellow" /><strong>Portfolio approval</strong><span>→</span><PixelIcon name="radar" color="google-green" /><strong>Immutable evidence</strong></div>
          </section>

          <section className="about-story-card about-fleet" aria-labelledby="fleet-heading">
            <div className="about-story-card__header"><PixelIcon name="satellite" size="md" color="google-yellow" glow /><div><span className="section-head__eyebrow">FORTIFIED ENTERPRISE FLEET</span><h2 id="fleet-heading" className="about-story-card__title">Specialists with names, contracts, and bounded authority</h2></div></div>
            <p className="about-story-card__text">This is not a swarm of interchangeable chatbots. Atlas routes a typed task to the specialist whose tools and authority match it; every handoff returns evidence to the same durable run.</p>
            <article className="about-fleet-command">
              <span className="about-fleet-command__icon"><PixelIcon name="branch" size="lg" color="google-blue" glow /></span>
              <div><span>ATLAS · GO CONTROL PLANE</span><strong>One fleet marshal, no invisible autonomy</strong><p>Dispatch, timeout, retry, cancellation, approval, and replay all remain observable at the run boundary.</p></div>
              <StatusBeacon status="active" label="DURABLE ROUTER" mode="pulsing" size="xs" />
            </article>
            <div className="about-agent-loop" aria-label="Governed agent workflow">
              {[
                ["01", "GOAL"], ["02", "TYPED DISPATCH"], ["03", "TOOL + EVIDENCE"], ["04", "HUMAN GATE"], ["05", "EXECUTE"], ["06", "RECONCILE"],
              ].map(([number, label], index) => <div className="about-agent-loop__step" key={number}><span>{number}</span><strong>{label}</strong>{index < 5 ? <i aria-hidden="true">→</i> : null}</div>)}
            </div>
            <div className="about-fleet-grid">
              {fleetAgents.map((agent) => <article className="about-agent-card" data-status={agent.status} key={agent.codename}>
                <header><span className={`about-tech-icon about-tech-icon--${agent.color}`}><PixelIcon name={agent.icon} size="sm" color={agent.color} /></span><div><span>{agent.codename}</span><h3>{agent.role}</h3></div><em>{agent.status === "operational" ? "CORE" : "HARDENING"}</em></header>
                <p>{agent.mission}</p>
                <footer><PixelIcon name="lock" size="xs" color={agent.color} /><span>{agent.boundary}</span></footer>
              </article>)}
            </div>
          </section>

          <section className="about-story-card" aria-labelledby="platform-heading">
            <div className="about-story-card__header"><PixelIcon name="server" size="md" color="google-green" glow /><div><span className="section-head__eyebrow">ENTERPRISE CONTROL PLANE</span><h2 id="platform-heading" className="about-story-card__title">A foundation that can become an institutional agent platform</h2></div></div>
            <p className="about-story-card__text">Each control names the working foundation in this repository and the explicit hardening step required for a production fleet. “Next” items are architectural targets, not demo claims.</p>
            <div className="about-platform-grid">
              {enterpriseControls.map((control) => <article className="about-platform-card" key={control.name}>
                <header><PixelIcon name={control.icon} size="sm" color="google-blue" /><h3>{control.name}</h3></header>
                <dl><div><dt>NOW</dt><dd>{control.now}</dd></div><div><dt>NEXT</dt><dd>{control.next}</dd></div></dl>
              </article>)}
            </div>
          </section>

          <section className="about-story-card" aria-labelledby="principles-heading">
            <div className="about-story-card__header"><PixelIcon name="shield-check" size="md" color="google-blue" glow /><h2 id="principles-heading" className="about-story-card__title">Design principles</h2></div>
            <div className="about-architecture-grid">{architecturePrinciples.map(([title, text]) => <article key={title} className="about-source-card"><h3 className="about-source-card__title">{title}</h3><p>{text}</p></article>)}</div>
          </section>

          <section className="about-story-card" aria-labelledby="creators-heading">
            <div className="about-story-card__header"><PixelIcon name="satellite" size="md" color="google-green" glow /><h2 id="creators-heading" className="about-story-card__title">Creators and contributors</h2></div>
            {creators?.length ? <div className="about-creators-grid">{creators.map((creator) => <article key={`${creator.name}-${creator.role ?? ""}`} className="creator-card"><h3 className="creator-card__name">{creator.name}</h3>{creator.role ? <span className="creator-card__role">{creator.role}</span> : null}{creator.affiliation ? <span className="creator-card__affiliation">{creator.affiliation}</span> : null}{creator.bio ? <p className="creator-card__bio">{creator.bio}</p> : null}{creator.profileUrl ? <a href={creator.profileUrl} target="_blank" rel="noopener noreferrer" className="site-footer__link">Profile →</a> : null}</article>)}</div> : <p className="about-story-card__text">No creator or contributor information has been supplied.</p>}
          </section>

          
        </div>
      
        <section className="about-architecture" aria-labelledby="arch-diagram-heading">
          <h2 id="arch-diagram-heading">System architecture</h2>
          <p>What is actually deployed and verified, not a target-state drawing. Green borders mark components confirmed running on 2026-08-31.</p>
          <ArchitectureDiagram />
        </section>
</main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl="/about" sourceRepoUrl={sourceRepoUrl} links={[{ label: "Overview", route: "/" }, ...(dashboardRoute ? [{ label: "Mission control", route: dashboardRoute }] : [])]} />
    </div>
  );
}
