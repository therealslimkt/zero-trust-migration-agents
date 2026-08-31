import type { MouseEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { PixelIcon, ReplayBadge, StatusBeacon, TerminalWindow, type ThemeMode } from "../../shared/ui/index";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
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
  const replayAvailable = hasReplay(demo);
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
  };

  return (
    <div className="public-page">
      <SiteHeader activeRoute="/" onNavigate={onNavigate} authStatus={authStatus} userName={userName} userEmail={userEmail} userPhoto={userPhoto} onSignInClick={onSignInClick} onSignOutClick={onSignOutClick} theme={theme} onThemeChange={onThemeChange} demo={demo} loginRoute={loginRoute} aboutRoute={aboutRoute} dashboardRoute={dashboardRoute} />
      <main id="main-content" className="public-main" tabIndex={-1}>
        <div className="public-container">
          <section className="landing-hero" aria-labelledby="hero-title">
            <div className="landing-hero__badge-group">
              {replayAvailable ? <ReplayBadge mode="replay" detail="owner-published synthetic recording" size="md" /> : <StatusBeacon status="neutral" label="PUBLIC REPLAY NOT SUPPLIED" mode="steady" size="sm" />}
            </div>
            <h1 id="hero-title" className="landing-hero__headline">A visual control surface for <span className="landing-hero__headline-gradient">governed migration work</span></h1>
            <p className="landing-hero__subtitle">Explore the architecture, connect an authenticated control surface, or open an exact synthetic recorded replay when an owner has published one. The page never substitutes sample activity for a real descriptor.</p>
            <div className="landing-hero__actions">
              {replayAvailable ? <a href={demo.route} className="landing-hero__btn landing-hero__btn--primary" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="play" size="xs" color="black" /><span>Open exact recorded replay</span></a> : null}
              {dashboardRoute ? <a href={dashboardRoute} className="landing-hero__btn landing-hero__btn--outline" onClick={(event) => navigate(event, dashboardRoute)}><PixelIcon name="satellite" size="xs" color="google-blue" /><span>Open mission control</span></a> : null}
              <a href="/lab/m4" className="landing-hero__btn landing-hero__btn--outline" onClick={(event) => navigate(event, "/lab/m4")}><PixelIcon name="database" size="xs" color="google-yellow" /><span>Open local cartridge lab</span></a>
              <a href={aboutRoute} className="landing-hero__btn landing-hero__btn--outline" onClick={(event) => navigate(event, aboutRoute)}><PixelIcon name="radar" size="xs" color="muted" /><span>Read architecture</span></a>
            </div>
          </section>

          <section className="landing-pipeline" aria-labelledby="capability-heading">
            <div className="section-head"><div><span className="section-head__eyebrow">CONTROL SURFACE</span><h2 id="capability-heading" className="section-head__title">Configured data speaks; absent data stays absent.</h2></div></div>
            <div className="landing-tech-grid">
              {capabilityCards.map((card, index) => <motion.article key={card.title} className="landing-tech-card" initial={reducedMotion ? false : { opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: reducedMotion ? 0 : index * 0.06 }}><PixelIcon name={card.icon} size="md" color={card.color} glow /><span className="landing-tech-card__role">{card.title}</span><p>{card.text}</p></motion.article>)}
            </div>
          </section>

          <section aria-labelledby="replay-heading">
            <TerminalWindow title="Public replay availability" breadcrumb="public/replay" accent="google-yellow" variant="glass" scanlines>
              <div className="landing-code-panel">
                <div><h2 id="replay-heading">{replayAvailable ? demo.title : "No replay descriptor supplied"}</h2><p>{replayAvailable ? "This link is an exact synthetic recorded replay selected by its owner. Its identifier and route come from the descriptor, not a page default." : "An exact synthetic recorded replay can be shown here only after the application receives an owner-published descriptor."}</p></div>
                {replayAvailable ? <a href={demo.route} className="landing-hero__btn landing-hero__btn--secondary" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="rewind" size="xs" color="google-yellow" /><span>Review replay</span></a> : null}
              </div>
            </TerminalWindow>
          </section>
        </div>
      </main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl={aboutRoute} sourceRepoUrl={sourceRepoUrl} links={[{ label: "About", route: aboutRoute }, ...(dashboardRoute ? [{ label: "Mission control", route: dashboardRoute }] : [])]} />
    </div>
  );
}
