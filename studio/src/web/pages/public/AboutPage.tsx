import type { MouseEvent } from "react";
import { PixelIcon, StatusBeacon, TerminalWindow, type PixelIconName, type ThemeMode } from "../../shared/ui/index";
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

/** Architecture narrative with owner-supplied creators and submission facts only. */
export function AboutPage({
  onNavigate,
  theme = "dark",
  onThemeChange,
  creators,
  submissionFacts,
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
  const entries = Object.entries(submissionFacts ?? {}).filter(([, value]) => Boolean(value));

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

          <section className="about-story-card" aria-labelledby="principles-heading">
            <div className="about-story-card__header"><PixelIcon name="shield-check" size="md" color="google-blue" glow /><h2 id="principles-heading" className="about-story-card__title">Design principles</h2></div>
            <div className="about-architecture-grid">{architecturePrinciples.map(([title, text]) => <article key={title} className="about-source-card"><h3 className="about-source-card__title">{title}</h3><p>{text}</p></article>)}</div>
          </section>

          <section className="about-story-card" aria-labelledby="facts-heading">
            <div className="about-story-card__header"><PixelIcon name="terminal" size="md" color="google-yellow" glow /><h2 id="facts-heading" className="about-story-card__title">Submission information</h2></div>
            {entries.length ? <dl className="submission-facts-table">{entries.map(([key, value]) => <div key={key}><dt>{key.replace(/([A-Z])/g, " $1")}</dt><dd>{value}</dd></div>)}</dl> : <p className="about-story-card__text">No submission information has been supplied.</p>}
          </section>

          <section className="about-story-card" aria-labelledby="creators-heading">
            <div className="about-story-card__header"><PixelIcon name="satellite" size="md" color="google-green" glow /><h2 id="creators-heading" className="about-story-card__title">Creators and contributors</h2></div>
            {creators?.length ? <div className="about-creators-grid">{creators.map((creator) => <article key={`${creator.name}-${creator.role ?? ""}`} className="creator-card"><h3 className="creator-card__name">{creator.name}</h3>{creator.role ? <span className="creator-card__role">{creator.role}</span> : null}{creator.affiliation ? <span className="creator-card__affiliation">{creator.affiliation}</span> : null}{creator.bio ? <p className="creator-card__bio">{creator.bio}</p> : null}{creator.profileUrl ? <a href={creator.profileUrl} target="_blank" rel="noopener noreferrer" className="site-footer__link">Profile →</a> : null}</article>)}</div> : <p className="about-story-card__text">No creator or contributor information has been supplied.</p>}
          </section>

          <TerminalWindow title="Public-data contract" breadcrumb="public/disclosure" accent="google-blue" variant="glass"><p className="about-story-card__text">Routes and public details are supplied by the embedding application. <a href="/" onClick={(event) => navigate(event, "/")}>Return to the overview</a>.</p></TerminalWindow>
        </div>
      </main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl="/about" sourceRepoUrl={sourceRepoUrl} links={[{ label: "Overview", route: "/" }, ...(dashboardRoute ? [{ label: "Mission control", route: dashboardRoute }] : [])]} />
    </div>
  );
}
