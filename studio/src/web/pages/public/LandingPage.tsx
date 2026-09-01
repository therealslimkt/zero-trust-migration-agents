import type { MouseEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { BrandBolt, PixelIcon, type ThemeMode } from "../../shared/ui/index";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
import { PixelPortrait, type PortraitId } from "../lab/PixelPortrait";
import { ClusterDecodePanel } from "./ClusterDecodePanel";
import "./public-pages.css";

export interface LandingPageProps {
  onNavigate?: (route: string) => void;
  theme?: ThemeMode;
  onThemeChange?: (theme: ThemeMode) => void;
  authStatus?: SiteAuthStatus;
  userName?: string | null;
  userEmail?: string | null;
  userPhoto?: string | null;
  onSignInClick?: () => void;
  onSignOutClick?: () => void;
  demo?: PublishedDemoDescriptor;
  dashboardRoute?: string;
  aboutRoute?: string;
  loginRoute?: string;
  sourceRepoUrl?: string;
}

const capabilityCards = [
  { icon: "cpu" as const, color: "google-blue" as const, title: "Private-source review", text: "Source handling is described by the run or connection that supplies it." },
  { icon: "sparkle" as const, color: "google-yellow" as const, title: "Gemini 3.7 Flash", text: "A planning-model label; active model selection is reported by configured execution data." },
  { icon: "branch" as const, color: "google-green" as const, title: "Governed execution", text: "The application can present plan, approval, and evidence state when it is supplied." },
  { icon: "database" as const, color: "google-blue" as const, title: "Destination review", text: "Destination details are shown only when a run publishes them." },
] as const;

function hasReplay(demo?: PublishedDemoDescriptor): demo is PublishedDemoDescriptor {
  return demo?.publication === "owner_published" && demo.kind === "synthetic_recorded_replay" && Boolean(demo.route);
}

/** Visual public entry point; it deliberately does not invent a run or operating state. */

const LANDING_BAD_GUYS: ReadonlyArray<{
  alias: string; portrait: PortraitId; source: string; crime: string; tell: string;
  team: ReadonlyArray<{ id: PortraitId; name: string; role: string }>;
}> = [
  { alias: "DAY ZERO", portrait: "day-zero", source: "JD Edwards EnterpriseOne 9.2 / IBM i",
    crime: "Dates that are not dates.",
    tell: "CYYDDD julian integers. 124001 is not January 24th, and 100000 is not a date at all.",
    team: [{ id: "analyst", name: "source_analyst_jde", role: "frozen single-turn profiler" },
           { id: "prisma", name: "PRISMA", role: "compiles the declarative cast" },
           { id: "vale", name: "VALE", role: "rejects any lossy narrowing" }] },
  { alias: "THE HEIR", portrait: "the-heir", source: "Microsoft Dynamics AX 2012 R3 / SQL Server",
    crime: "Children of parents that no longer exist.",
    tell: "64-bit RecId table inheritance. A derived row whose base row is gone still looks valid.",
    team: [{ id: "analyst", name: "source_analyst_ax", role: "resolves the inheritance chain" },
           { id: "vale", name: "VALE", role: "fails closed on orphan-derived rows" },
           { id: "ledger", name: "LEDGER", role: "reconciles accepted vs rejected" }] },
  { alias: "ALIAS", portrait: "alias", source: "Oracle E-Business Suite / Oracle 19c",
    crime: "Real columns wearing a disguise.",
    tell: "ATTRIBUTE1..15 descriptive flexfields whose meaning lives in a separate FND catalog.",
    team: [{ id: "analyst", name: "source_analyst_oracle", role: "reads FND flexfield context" },
           { id: "prisma", name: "PRISMA", role: "emits typed output columns" },
           { id: "atlas", name: "ATLAS", role: "coordinates, never approves" }] },
];

export function LandingPage({
  onNavigate,
  theme = "dark",
  onThemeChange,
  authStatus = "unconfigured",
  userName,
  userEmail,
  userPhoto,
  onSignInClick,
  onSignOutClick,
  demo,
  dashboardRoute,
  aboutRoute = "/about",
  loginRoute = "/login",
  sourceRepoUrl,
}: LandingPageProps) {
  const reducedMotion = useReducedMotion();
  void hasReplay;
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  };

  void navigate;

  return (
    <div className="public-page">
      <SiteHeader activeRoute="/" onNavigate={onNavigate} authStatus={authStatus} userName={userName} userEmail={userEmail} userPhoto={userPhoto} onSignInClick={onSignInClick} onSignOutClick={onSignOutClick} theme={theme} onThemeChange={onThemeChange} demo={demo} loginRoute={loginRoute} aboutRoute={aboutRoute} dashboardRoute={dashboardRoute} />
      <main id="main-content" className="public-main" tabIndex={-1}>
        <div className="public-container">
          <section className="landing-hero" aria-labelledby="hero-title">
            <h1 id="hero-title" className="landing-hero__headline"><span className="landing-hero__headline-gradient">Set your data free!</span></h1>
            <p className="landing-hero__tagline">Let insight strike.<span className="landing-hero__bolt" aria-hidden="true"><BrandBolt title="Keraun" /></span><b>Open source. Free of charge.</b></p>
            <p className="landing-hero__promise">Prove the move. Forge the plugin. Grow the fleet.</p>
            <p className="landing-hero__subtitle">Free valuable data from legacy systems without paying for a permanent middleware layer. Prove a migration in an isolated sandbox, inspect the evidence, forge a portable execution plugin, and promote validated expertise into a discoverable enterprise agent.</p>
            <div className="landing-hero__actions">
                            <a href="/mission-control" className="landing-hero__btn landing-hero__btn--outline"><PixelIcon name="satellite" size="xs" color="google-blue" /><span>Open Mission Control</span></a>
              <a href="/architecture.html" target="_blank" rel="noreferrer" className="landing-hero__btn landing-hero__btn--outline"><PixelIcon name="radar" size="xs" color="muted" /><span>Architecture diagram</span></a>
            </div>
          </section>

          <section className="landing-badguys" aria-labelledby="badguys-heading">
            <div className="landing-control__heading">
              <span className="landing-control__eyebrow"><PixelIcon name="bug" size="xs" color="google-red" />THE ADVERSARIES</span>
              <h2 id="badguys-heading">Three legacy systems that refuse to let go.</h2>
              <p>Each one hides its data behind a different, well-documented pathology. Keraun assigns a least-authority agent team to each.</p>
            </div>
            <div className="landing-badguys__grid">
              {LANDING_BAD_GUYS.map((v) => (
                <article key={v.alias} className="landing-villain">
                  <div className="landing-villain__top">
                    <PixelPortrait id={v.portrait} size={92} title={v.alias} />
                    <div>
                      <h3>{v.alias}</h3>
                      <p className="landing-villain__src">{v.source}</p>
                    </div>
                  </div>
                  <p className="landing-villain__crime">{v.crime}</p>
                  <p className="landing-villain__tell">{v.tell}</p>
                  <ul className="landing-villain__team">
                    {v.team.map((a) => (
                      <li key={a.name}><PixelPortrait id={a.id} size={30} title={a.name} /><span><b>{a.name}</b>{a.role}</span></li>
                    ))}
                  </ul>
                </article>
              ))}
            </div>
          </section>

          <ClusterDecodePanel />

          <section className="landing-pipeline" aria-labelledby="capability-heading">
            <div className="landing-control__heading">
              <span className="landing-control__eyebrow"><PixelIcon name="sparkle" size="xs" color="google-yellow" />CONTROL SURFACE</span>
              <h2 id="capability-heading">Evidence appears when the system can prove it.</h2>
              <p>Configured data speaks; absent data stays absent. That keeps the canvas useful without pretending a migration is in flight.</p>
            </div>
            <div className="landing-tech-grid">
              {capabilityCards.map((card, index) => <motion.article key={card.title} className="landing-tech-card" initial={reducedMotion ? false : { opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: reducedMotion ? 0 : index * 0.06 }}>
                <div className="landing-tech-card__top"><span className="landing-tech-card__icon"><PixelIcon name={card.icon} size="md" color={card.color} glow /></span><span className="landing-tech-card__index">0{index + 1}</span></div>
                <h3>{card.title}</h3>
                <p>{card.text}</p>
              </motion.article>)}
            </div>
          </section>


        </div>
      </main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl={aboutRoute} sourceRepoUrl={sourceRepoUrl} links={[{ label: "About", route: aboutRoute }, ...(dashboardRoute ? [{ label: "Mission control", route: dashboardRoute }] : [])]} />
    </div>
  );
}
