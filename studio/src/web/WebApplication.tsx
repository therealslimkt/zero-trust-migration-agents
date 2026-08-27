import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createContext, lazy, Suspense, useContext, useEffect, useState, type ReactNode } from "react";
import { createBrowserRouter, Navigate, RouterProvider, useLocation, useNavigate } from "react-router";

import { RecordedDemoClient } from "./client";
import { AuthProvider, ProtectedRoute, readSafeReturnTo, useAuth } from "./features/auth";
import type { ThemeMode } from "./shared/ui";
import type { PublishedDemoDescriptor } from "./widgets/site";
import "./shared/styles/index.css";

const LandingPage = lazy(() => import('./pages/public/LandingPage').then((module) => ({ default: module.LandingPage })))
const LoginPage = lazy(() => import('./pages/public/LoginPage').then((module) => ({ default: module.LoginPage })))
const AboutPage = lazy(() => import('./pages/public/AboutPage').then((module) => ({ default: module.AboutPage })))
const NotFoundPage = lazy(() => import('./pages/public/NotFoundPage').then((module) => ({ default: module.NotFoundPage })))
const RecordedDemoRoute = lazy(() => import('./pages/replay/RecordedDemoRoute').then((module) => ({ default: module.RecordedDemoRoute })))
const DashboardRoute = lazy(() => import('./pages/protected/ProtectedRoutes').then((module) => ({ default: module.DashboardRoute })))
const LiveRunRoute = lazy(() => import('./pages/protected/ProtectedRoutes').then((module) => ({ default: module.LiveRunRoute })))
const SourceDetailRoute = lazy(() => import('./pages/protected/ProtectedRoutes').then((module) => ({ default: module.SourceDetailRoute })))
const SourceOnboardingRoute = lazy(() => import('./pages/protected/ProtectedRoutes').then((module) => ({ default: module.SourceOnboardingRoute })))
const CloudSettingsRoute = lazy(() => import('./pages/protected/ProtectedRoutes').then((module) => ({ default: module.CloudSettingsRoute })))

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });
const publicClient = new RecordedDemoClient();

interface AppearanceValue {
  readonly theme: ThemeMode;
  readonly setTheme: (theme: ThemeMode) => void;
}

const AppearanceContext = createContext<AppearanceValue | null>(null);

function AppearanceProvider({ children }: { readonly children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === "undefined") return "dark";
    return window.localStorage.getItem("ztm-theme") === "light" ? "light" : "dark";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("ztm-theme", theme);
  }, [theme]);
  return <AppearanceContext.Provider value={{ theme, setTheme }}>{children}</AppearanceContext.Provider>;
}

function useAppearance(): AppearanceValue {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error("AppearanceProvider is required.");
  return value;
}

function usePublishedDemo(): PublishedDemoDescriptor | undefined {
  const query = useQuery({ queryKey: ["published-demos"], queryFn: () => publicClient.list(), staleTime: 60_000, retry: 1 });
  const demo = query.data?.demos[0];
  return demo ? {
    publication: "owner_published",
    kind: "synthetic_recorded_replay",
    route: `/demo/${encodeURIComponent(demo.demoId)}`,
    title: demo.title,
    demoId: demo.demoId,
  } : undefined;
}

function usePublicPageProps() {
  const auth = useAuth();
  const appearance = useAppearance();
  const navigate = useNavigate();
  const demo = usePublishedDemo();
  return {
    auth,
    appearance,
    demo,
    navigate,
    shared: {
      onNavigate: (route: string) => navigate(route),
      theme: appearance.theme,
      onThemeChange: appearance.setTheme,
      authStatus: auth.status,
      userName: auth.user?.displayName,
      userEmail: auth.user?.email,
      userPhoto: auth.user?.photoURL,
      onSignInClick: auth.status === "anonymous" ? () => void auth.signInWithGoogle().catch(() => undefined) : undefined,
      onSignOutClick: auth.status === "authenticated" ? () => void auth.signOut().catch(() => undefined) : undefined,
      demo,
      dashboardRoute: "/dashboard",
    },
  };
}

function HomeRoute() {
  const legacyRunId = new URLSearchParams(useLocation().search).get("runId")?.trim();
  const { shared } = usePublicPageProps();
  if (legacyRunId) return <Navigate to={`/runs/${encodeURIComponent(legacyRunId)}`} replace />;
  return <LandingPage {...shared} />;
}

function AboutRoute() {
  const { shared } = usePublicPageProps();
  return <AboutPage {...shared} />;
}

function LoginRoute() {
  const { auth, appearance, demo, navigate } = usePublicPageProps();
  const location = useLocation();
  const returnRoute = readSafeReturnTo(location.state, "/dashboard");
  useEffect(() => {
    if (auth.status === "authenticated") navigate(returnRoute, { replace: true });
  }, [auth.status, navigate, returnRoute]);
  return <LoginPage onNavigate={(route) => navigate(route)} theme={appearance.theme} onThemeChange={appearance.setTheme} authStatus={auth.status} userName={auth.user?.displayName} userEmail={auth.user?.email} userPhoto={auth.user?.photoURL} onSignIn={auth.status === "anonymous" ? () => void auth.signInWithGoogle().catch(() => undefined) : undefined} onSignOut={auth.status === "authenticated" ? () => void auth.signOut().catch(() => undefined) : undefined} errorMessage={auth.error?.message} returnRoute={returnRoute} dashboardRoute="/dashboard" demo={demo} />;
}

function Protected({ children }: { readonly children: ReactNode }) {
  return <ProtectedRoute initializingFallback={<RouteNotice title="Preparing your identity" detail="Waiting for the configured Firebase session." />} unconfiguredFallback={<RouteNotice title="Authentication is not configured" detail="Supply the Firebase public configuration before opening private run data." />} errorFallback={<RouteNotice title="Identity verification failed" detail="Private run data remains unavailable." />}>{children}</ProtectedRoute>;
}

function RouteNotice({ title, detail }: { readonly title: string; readonly detail: string }) {
  return <main className="web-route-notice mission-control-root"><section><span>MISSION CONTROL</span><h1>{title}</h1><p>{detail}</p></section></main>;
}

function NotFoundRoute() {
  const { shared } = usePublicPageProps();
  return <NotFoundPage {...shared} requestedPath={useLocation().pathname} />;
}

const router = createBrowserRouter([
  { path: "/", element: <HomeRoute /> },
  { path: "/login", element: <LoginRoute /> },
  { path: "/about", element: <AboutRoute /> },
  { path: "/demo/:demoId", element: <RecordedDemoRoute /> },
  { path: "/dashboard", element: <Protected><DashboardRoute /></Protected> },
  { path: "/runs/:runId", element: <Protected><LiveRunRoute /></Protected> },
  { path: "/runs/:runId/sources/:sourceId", element: <Protected><SourceDetailRoute /></Protected> },
  { path: "/sources/new", element: <Protected><SourceOnboardingRoute /></Protected> },
  { path: "/settings/cloud", element: <Protected><CloudSettingsRoute /></Protected> },
  { path: "*", element: <NotFoundRoute /> },
]);

export function WebApplication() {
  return <QueryClientProvider client={queryClient}><AuthProvider><AppearanceProvider><Suspense fallback={<RouteNotice title="Loading control surface" detail="Preparing the requested application view." />}><RouterProvider router={router} /></Suspense></AppearanceProvider></AuthProvider></QueryClientProvider>;
}
