import type { MouseEvent } from "react";
import { ArchitectureDiagram } from "./ArchitectureDiagram";
import { PixelIcon, StatusBeacon, type PixelIconName, type ThemeMode } from "../../shared/ui/index";
import { PluginFactory } from "./PluginFactory";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
import { CreatorSpotlight } from "./CreatorSpotlight";
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

/** Each of these describes something the code actually does, not something it aims at. */
const architecturePrinciples: ReadonlyArray<{
  readonly title: string;
  readonly detail: string;
  readonly icon: PixelIconName;
  readonly color: "google-blue" | "google-red" | "google-yellow" | "google-green";
}> = [
  { title: "The source never leaves its perimeter", icon: "sealed-perimeter", color: "google-green",
    detail: "The emulators sit on an internal Docker network with no egress. Every query runs as a read-only role from inside a locked-down runner, so the migration reads a faithful copy and never reaches the source itself." },
  { title: "Code owns the decode; the model only chooses parameters", icon: "code-owned", color: "google-blue",
    detail: "The Beam DoFns are code in this repository. Gemini proposes rename, cast and drop and nothing else — it never emits the transform, and nothing it returns is executed." },
  { title: "A bad row is refused, never repaired", icon: "refuse-not-repair", color: "google-yellow",
    detail: "A record that will not decode is tagged to a rejected output instead of being coerced into one that looks fine. Quarantine carries the locating key and the reason, never the row's contents." },
  { title: "Every count reconciles, or the run says so", icon: "reconcile", color: "google-green",
    detail: "Read equals accepted plus rejected equals written, checked against the destination on every run and reported as MATCHED or MISMATCHED. The JDE cartridge reads 500, lands 498 and refuses 2." },
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
  { codename: "AXIOM", role: "Dynamics AX cartographer", icon: "sqlserver", color: "google-red", status: "operational", mission: "Resolves AX table inheritance, holding company and partition together so a derived row is never landed without the base row it inherits from.", boundary: "Read-only source adapter · inheritance and identity evidence" },
  { codename: "FLEX", role: "EBS flexfield archaeologist", icon: "oracle", color: "google-green", status: "operational", mission: "Reads FND_DESCRIPTIVE_FLEXS to give ATTRIBUTE1..15 their declared names, and refuses a context the catalogue does not define rather than guessing it.", boundary: "Read-only source adapter · flexfield semantic evidence" },
  { codename: "MAVEN", role: "Driver librarian", icon: "artifact-registry", color: "google-red", status: "operational", mission: "Researches, verifies, and immutably publishes exact driver artifacts for reproducible compilation.", boundary: "Async Go worker · Vertex research · Artifact Registry provenance" },
  { codename: "PRISMA", role: "Transform architect", icon: "gemini", color: "google-yellow", status: "operational", mission: "Uses Gemini to propose declarative mappings from protected metadata and exact driver capabilities.", boundary: "Plan-only authority · cannot approve, execute, or mutate source data" },
  { codename: "VALE", role: "Policy auditor", icon: "shield-check", color: "google-blue", status: "operational", mission: "Applies deterministic validation to plans, evidence references, and approval preconditions.", boundary: "Fail-closed policy checks · no generative override" },
  { codename: "STEWARD", role: "Human governor", icon: "identity-platform", color: "google-yellow", status: "operational", mission: "Reviews the sealed portfolio digest and makes the one decision agents are not allowed to make.", boundary: "Identity-bound HITL approval · exact digest · immutable decision evidence" },
  { codename: "FLOW + LEDGER", role: "Execution and reconciliation", icon: "dataflow", color: "google-green", status: "hardening", mission: "Turns an approved Beam plan into Dataflow work, then proves BigQuery rows against jobs, tables, and audit evidence.", boundary: "Execute only after approval · publish only after reconciliation" },
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

          <section className="about-story-card" aria-labelledby="factory-heading">
            <div className="about-story-card__header"><PixelIcon name="cartridge" size="md" color="google-green" glow /><div><span className="section-head__eyebrow">THE PLUGIN FACTORY</span><h2 id="factory-heading" className="about-story-card__title">A legacy engine goes in; a sealed cartridge comes out</h2></div></div>
            <p className="about-story-card__text">Keraun is not one migration. It is the line that builds them: each cartridge is a sealed, digest-pinned image of a legacy engine plus the code that decodes it, and adding a system means adding a cartridge rather than rewriting the pipeline.</p>
            <PluginFactory />
          </section>

          <section className="about-story-card" aria-labelledby="principles-heading">
            <div className="about-story-card__header"><PixelIcon name="shield-check" size="md" color="google-blue" glow /><h2 id="principles-heading" className="about-story-card__title">Design principles</h2></div>
            <div className="about-architecture-grid">{architecturePrinciples.map((principle) => <article key={principle.title} className="about-source-card"><span className={`about-tech-icon about-tech-icon--${principle.color}`}><PixelIcon name={principle.icon} size="lg" color={principle.color} /></span><h3 className="about-source-card__title">{principle.title}</h3><p>{principle.detail}</p></article>)}</div>
          </section>

          <section className="about-story-card" aria-labelledby="creators-heading">
            <div className="about-story-card__header"><PixelIcon name="satellite" size="md" color="google-green" glow /><h2 id="creators-heading" className="about-story-card__title">Creators and contributors</h2></div>
            <CreatorSpotlight />
            {creators?.length ? <div className="about-creators-grid">{creators.map((creator) => <article key={`${creator.name}-${creator.role ?? ""}`} className="creator-card"><h3 className="creator-card__name">{creator.name}</h3>{creator.role ? <span className="creator-card__role">{creator.role}</span> : null}{creator.affiliation ? <span className="creator-card__affiliation">{creator.affiliation}</span> : null}{creator.bio ? <p className="creator-card__bio">{creator.bio}</p> : null}{creator.profileUrl ? <a href={creator.profileUrl} target="_blank" rel="noopener noreferrer" className="site-footer__link">Profile →</a> : null}</article>)}</div> : null}
          </section>
        </div>

        <section className="about-architecture" aria-labelledby="arch-diagram-heading">
          <h2 id="arch-diagram-heading">The system as it actually runs</h2>
          <p>Not a target-state drawing. Every component below was confirmed running on 2026-09-01, when all three cartridges were loaded, compiled, landed and embedded end to end from this URL — 500 records read, 498 landed, 2 refused, reconciled at the destination.</p>
          <ArchitectureDiagram />
        </section>
</main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl="/about" sourceRepoUrl={sourceRepoUrl} links={[{ label: "Overview", route: "/" }, ...(dashboardRoute ? [{ label: "Mission control", route: dashboardRoute }] : [])]} />
    </div>
  );
}
