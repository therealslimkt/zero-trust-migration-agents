import type { MouseEvent } from "react";
import { PixelIcon, StatusBeacon, type ThemeMode } from "../../shared/ui/index";
import { SiteFooter } from "../../widgets/site/SiteFooter";
import { SiteHeader, type PublishedDemoDescriptor, type SiteAuthStatus } from "../../widgets/site/SiteHeader";
import "./public-pages.css";

export interface LoginPageProps {
  onNavigate?: (route: string) => void;
  authStatus?: SiteAuthStatus;
  userName?: string | null;
  userEmail?: string | null;
  userPhoto?: string | null;
  onSignIn?: () => void;
  onSignOut?: () => void;
  errorMessage?: string | null;
  theme?: ThemeMode;
  onThemeChange?: (theme: ThemeMode) => void;
  returnRoute?: string;
  demo?: PublishedDemoDescriptor;
  dashboardRoute?: string;
  aboutRoute?: string;
}

function hasReplay(demo?: PublishedDemoDescriptor): demo is PublishedDemoDescriptor {
  return demo?.publication === "owner_published" && demo.kind === "synthetic_recorded_replay" && Boolean(demo.route);
}

/** Firebase sign-in explainer. Sign-in is intentionally disabled until configured by the host application. */
export function LoginPage({
  onNavigate,
  authStatus = "unconfigured",
  userName,
  userEmail,
  userPhoto,
  onSignIn,
  onSignOut,
  errorMessage,
  theme = "dark",
  onThemeChange,
  returnRoute,
  demo,
  dashboardRoute,
  aboutRoute = "/about",
}: LoginPageProps) {
  const replayAvailable = hasReplay(demo);
  const canSignIn = authStatus === "anonymous" && Boolean(onSignIn);
  const isAuthenticated = authStatus === "authenticated";
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string) => {
    if (!onNavigate) return;
    event.preventDefault();
    onNavigate(route);
  };

  return (
    <div className="public-page">
      <SiteHeader activeRoute="/login" onNavigate={onNavigate} authStatus={authStatus} userName={userName} userEmail={userEmail} userPhoto={userPhoto} onSignInClick={onSignIn} onSignOutClick={onSignOut} theme={theme} onThemeChange={onThemeChange} demo={demo} aboutRoute={aboutRoute} dashboardRoute={dashboardRoute} skipTargetId="login-content" />
      <main id="login-content" className="public-main login-page-container" tabIndex={-1}>
        <section className="login-chassis" aria-labelledby="login-title">
          <header className="login-chassis__header"><PixelIcon name={isAuthenticated ? "shield-check" : "lock"} size="lg" color={isAuthenticated ? "google-green" : "google-blue"} glow /><h1 id="login-title" className="login-chassis__title">{isAuthenticated ? "Authenticated session" : "Sign in to migration control"}</h1><p className="login-chassis__tagline">Identity is configured by the hosting application.</p></header>
          <div className="login-chassis__body">
            {authStatus === "error" || errorMessage ? <div className="login-error-banner" role="alert"><PixelIcon name="alert-triangle" size="xs" color="google-red" /><span>{errorMessage || "Sign-in could not be completed."}</span></div> : null}
            {isAuthenticated ? <>
              <div className="login-user-card">{userPhoto ? <img src={userPhoto} alt="" className="login-user-card__avatar" /> : <span className="login-user-card__avatar-fallback">{(userName || userEmail || "?")[0]?.toUpperCase()}</span>}<div className="login-user-card__info"><span className="login-user-card__name">{userName || userEmail || "Authenticated session"}</span><StatusBeacon status="active" label="SESSION VERIFIED" size="xs" mode="steady" /></div></div>
              {returnRoute || dashboardRoute ? <a href={returnRoute || dashboardRoute} className="landing-hero__btn landing-hero__btn--primary" onClick={(event) => navigate(event, returnRoute || dashboardRoute || "/")}><PixelIcon name="satellite" size="xs" color="black" /><span>Continue</span></a> : null}
              {onSignOut ? <button type="button" className="landing-hero__btn landing-hero__btn--outline" onClick={onSignOut}>Sign out</button> : null}
            </> : <>
              <button type="button" className="login-google-btn" onClick={onSignIn} disabled={!canSignIn} aria-describedby="token-flow"><PixelIcon name="key" size="sm" color="google-blue" /><span>{authStatus === "unconfigured" ? "Sign-in not configured" : authStatus === "initializing" ? "Preparing sign-in" : "Sign in with Firebase"}</span></button>
              <div id="token-flow" className="login-security-notice"><strong>IDENTITY FLOW</strong><p>Firebase obtains an ID token. The browser sends that token to a same-origin endpoint, where the backend-for-frontend verifies it before creating application session state. The page does not expose provider secrets, cloud credentials, or authorization scopes.</p></div>
              {authStatus === "unconfigured" ? <p className="telemetry-mono">SIGN-IN IS DISABLED UNTIL FIREBASE CONFIGURATION IS SUPPLIED.</p> : null}
              {replayAvailable ? <a href={demo.route} className="site-footer__link" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="play" size="xs" color="google-yellow" /><span>Open exact synthetic recorded replay</span></a> : null}
            </>}
          </div>
        </section>
      </main>
      <SiteFooter onNavigate={onNavigate} demo={demo} documentationUrl={aboutRoute} links={[{ label: "Overview", route: "/" }, { label: "About", route: aboutRoute }]} />
    </div>
  );
}
