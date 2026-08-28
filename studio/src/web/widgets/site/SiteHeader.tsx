import { useId, useState, type MouseEvent } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { PixelIcon, ThemeToggle, type PixelIconName, type ThemeMode } from "../../shared/ui/index";
import "./site-widgets.css";

export type SiteNavMode = "recorded_demo" | "live" | "public";
export type SiteAuthStatus = "initializing" | "anonymous" | "authenticated" | "error" | "unconfigured";

/** A replay may be advertised only after an owner supplies this descriptor. */
export interface PublishedDemoDescriptor {
  readonly publication: "owner_published";
  readonly kind: "synthetic_recorded_replay";
  readonly route: string;
  readonly title: string;
  readonly demoId?: string;
}

export interface NavItem {
  readonly id: string;
  readonly label: string;
  readonly route: string;
  readonly icon?: PixelIconName;
}

export interface SiteHeaderProps {
  activeRoute?: string;
  onNavigate?: (route: string) => void;
  brandTitle?: string;
  tagline?: string;
  mode?: SiteNavMode;
  authStatus?: SiteAuthStatus;
  userName?: string | null;
  userEmail?: string | null;
  userPhoto?: string | null;
  onSignInClick?: () => void;
  onSignOutClick?: () => void;
  theme?: ThemeMode;
  onThemeChange?: (theme: ThemeMode) => void;
  demo?: PublishedDemoDescriptor;
  loginRoute?: string;
  aboutRoute?: string;
  dashboardRoute?: string;
  cloudSettingsRoute?: string;
  skipTargetId?: string;
  className?: string;
}

function isPublishedReplay(demo?: PublishedDemoDescriptor): demo is PublishedDemoDescriptor {
  return demo?.publication === "owner_published" && demo.kind === "synthetic_recorded_replay" && Boolean(demo.route);
}

/** Shared public navigation. It intentionally has no default replay identity or route. */
export function SiteHeader({
  activeRoute = "/",
  onNavigate,
  brandTitle = "MIGRATION CONTROL",
  tagline = "GOVERNED DATA MOVEMENT",
  mode = "public",
  authStatus = "unconfigured",
  userName,
  userEmail,
  userPhoto,
  onSignInClick,
  onSignOutClick,
  theme,
  onThemeChange,
  demo,
  loginRoute = "/login",
  aboutRoute = "/about",
  dashboardRoute,
  cloudSettingsRoute,
  skipTargetId = "main-content",
  className = "",
}: SiteHeaderProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const reducedMotion = useReducedMotion();
  const drawerId = useId();
  const replayAvailable = isPublishedReplay(demo);
  const canSignIn = authStatus === "anonymous" && Boolean(onSignInClick);
  const signedInCloudSettingsRoute = authStatus === "authenticated" ? (cloudSettingsRoute ?? "/settings/cloud") : undefined;
  const navItems: readonly NavItem[] = [
    { id: "home", label: "Overview", route: "/", icon: "shield-check" },
    ...(replayAvailable ? [{ id: "replay", label: "Recorded replay", route: demo.route, icon: "play" as const }] : []),
    ...(dashboardRoute ? [{ id: "dashboard", label: "Mission control", route: dashboardRoute, icon: "satellite" as const }] : []),
    ...(signedInCloudSettingsRoute ? [{ id: "cloud", label: "Google Cloud", route: signedInCloudSettingsRoute, icon: "google-cloud" as const }] : []),
    ...(aboutRoute ? [{ id: "about", label: "About", route: aboutRoute, icon: "radar" as const }] : []),
  ];

  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
    setMobileOpen(false);
  };

  const navLink = (item: NavItem, mobile = false) => {
    const active = item.route === "/" ? activeRoute === "/" : activeRoute.startsWith(item.route);
    return (
      <a href={item.route} className={mobile ? "site-header__mobile-nav-link" : "site-header__nav-link"} aria-current={active ? "page" : undefined} onClick={(event) => navigate(event, item.route)}>
        {item.icon ? <PixelIcon name={item.icon} size="xs" color={active ? "google-blue" : "secondary"} /> : null}
        <span>{item.label}</span>
      </a>
    );
  };

  return (
    <>
      <a href={`#${skipTargetId}`} className="site-skip-link">Skip to main content</a>
      <header role="banner" className={`site-header ${className}`.trim()}>
        <div className="site-header__container">
          <a href="/" className="site-header__brand" onClick={(event) => navigate(event, "/")} aria-label={`${brandTitle} home`}>
            <span className="site-header__brand-icon"><PixelIcon name="shield-check" size="md" color="google-blue" glow /></span>
            <span className="site-header__brand-text"><span className="site-header__brand-title">{brandTitle}</span><span className="site-header__brand-tag">{tagline}{mode === "recorded_demo" ? " · REPLAY" : ""}</span></span>
          </a>
          <nav className="site-header__nav" aria-label="Main navigation"><ul className="site-header__nav-list">{navItems.map((item) => <li key={item.id}>{navLink(item)}</li>)}</ul></nav>
          <div className="site-header__actions">
            <ThemeToggle theme={theme} onThemeChange={onThemeChange} size="sm" variant="button" accent="rainbow" ariaLabel="Toggle site color theme" />
            {replayAvailable ? <a href={demo.route} className="site-header__btn site-header__btn--demo" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="play" size="xs" color="google-yellow" glow /><span>Recorded replay</span></a> : null}
            {authStatus === "authenticated" ? (
              <div className="site-header__user" title={userEmail || userName || "Authenticated session"}>
                {userPhoto ? <img src={userPhoto} alt="" className="site-header__user-avatar" /> : <span className="site-header__user-avatar-fallback">{(userName || userEmail || "?")[0]?.toUpperCase()}</span>}
                <span className="site-header__user-info"><span className="site-header__user-name">{userName || userEmail || "Authenticated session"}</span><span className="site-header__user-tag">VERIFIED</span></span>
                {onSignOutClick ? <button type="button" className="site-header__btn" onClick={onSignOutClick}>Sign out</button> : null}
              </div>
            ) : authStatus === "unconfigured" ? <button type="button" className="site-header__btn" disabled title="Sign-in has not been configured">Sign-in unavailable</button> : canSignIn ? <button type="button" className="site-header__btn site-header__btn--primary" onClick={onSignInClick}><PixelIcon name="key" size="xs" color="white" /><span>Sign in</span></button> : <a href={loginRoute} className="site-header__btn site-header__btn--primary" onClick={(event) => navigate(event, loginRoute)}><span>Sign in</span></a>}
            <button type="button" className="site-header__mobile-toggle" aria-expanded={mobileOpen} aria-controls={drawerId} aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"} onClick={() => setMobileOpen((open) => !open)}><PixelIcon name={mobileOpen ? "cross-pixel" : "terminal"} size="sm" color="google-blue" /></button>
          </div>
        </div>
        <AnimatePresence>{mobileOpen ? <motion.div id={drawerId} className="site-header__mobile-drawer site-header__mobile-drawer--open" initial={reducedMotion ? false : { opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: reducedMotion ? 0 : 0.2 }}><nav aria-label="Mobile navigation"><ul className="site-header__mobile-nav-list">{navItems.map((item) => <li key={item.id}>{navLink(item, true)}</li>)}</ul></nav>{authStatus === "unconfigured" ? <p className="telemetry-mono">SIGN-IN NOT CONFIGURED</p> : null}</motion.div> : null}</AnimatePresence>
      </header>
    </>
  );
}
