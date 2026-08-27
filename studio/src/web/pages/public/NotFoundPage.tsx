import type { MouseEvent } from "react";
import { PixelIcon, StatusBeacon, TerminalWindow, type ThemeMode } from "../../shared/ui/index";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
import "./public-pages.css";

export interface NotFoundPageProps {
  onNavigate?: (route: string) => void;
  theme?: ThemeMode;
  onThemeChange?: (theme: ThemeMode) => void;
  requestedPath?: string;
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
}

function hasReplay(demo?: PublishedDemoDescriptor): demo is PublishedDemoDescriptor {
  return demo?.publication === "owner_published" && demo.kind === "synthetic_recorded_replay" && Boolean(demo.route);
}

/** Route recovery surface without fabricated telemetry, timestamps, or route inventories. */
export function NotFoundPage({
  onNavigate,
  theme = "dark",
  onThemeChange,
  requestedPath,
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
}: NotFoundPageProps) {
  const currentPath = requestedPath || (typeof window === "undefined" ? "Unknown route" : window.location.pathname);
  const replayAvailable = hasReplay(demo);
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
  };

  return (
    <div className="public-page">
      <SiteHeader activeRoute="" onNavigate={onNavigate} authStatus={authStatus} userName={userName} userEmail={userEmail} userPhoto={userPhoto} onSignInClick={onSignInClick} onSignOutClick={onSignOutClick} theme={theme} onThemeChange={onThemeChange} demo={demo} loginRoute={loginRoute} aboutRoute={aboutRoute} dashboardRoute={dashboardRoute} skipTargetId="not-found-content" />
      <main id="not-found-content" className="public-main not-found-container" tabIndex={-1}>
        <div className="not-found-chassis">
          <TerminalWindow title="Route unavailable" breadcrumb="public/router" accent="google-red" variant="elevated" scanlines cornerBrackets badge={<StatusBeacon status="warning" label="NO MATCH" mode="steady" size="xs" />}>
            <p className="about-story-card__text">The requested route is not available in this application view.</p>
            <p className="telemetry-mono">REQUESTED PATH: {currentPath}</p>
            <p className="about-story-card__text">Choose one of the supplied destinations below. This view does not infer service status, authentication, or replay availability.</p>
          </TerminalWindow>
          <div className="not-found-actions">
            <a href="/" className="landing-hero__btn landing-hero__btn--primary" onClick={(event) => navigate(event, "/")}><PixelIcon name="shield-check" size="xs" color="black" /><span>Return to overview</span></a>
            {replayAvailable ? <a href={demo.route} className="landing-hero__btn landing-hero__btn--secondary" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="play" size="xs" color="google-yellow" /><span>Open recorded replay</span></a> : null}
            {dashboardRoute ? <a href={dashboardRoute} className="landing-hero__btn landing-hero__btn--outline" onClick={(event) => navigate(event, dashboardRoute)}><PixelIcon name="satellite" size="xs" color="google-blue" /><span>Mission control</span></a> : null}
            <a href={aboutRoute} className="landing-hero__btn landing-hero__btn--outline" onClick={(event) => navigate(event, aboutRoute)}><PixelIcon name="radar" size="xs" color="muted" /><span>About</span></a>
          </div>
        </div>
      </main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl={aboutRoute} links={[{ label: "Overview", route: "/" }, { label: "About", route: aboutRoute }]} />
    </div>
  );
}
