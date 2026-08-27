import type { MouseEvent } from "react";
import { PixelIcon } from "../../shared/ui/index";
import type { PublishedDemoDescriptor } from "./SiteHeader";
import "./site-widgets.css";

export interface FooterLinkItem {
  readonly label: string;
  readonly route: string;
  readonly isExternal?: boolean;
}

export interface SiteFooterProps {
  onNavigate?: (route: string) => void;
  productName?: string;
  links?: readonly FooterLinkItem[];
  demo?: PublishedDemoDescriptor;
  sourceRepoUrl?: string;
  documentationUrl?: string;
  className?: string;
}

function hasPublishedReplay(demo?: PublishedDemoDescriptor): demo is PublishedDemoDescriptor {
  return demo?.publication === "owner_published" && demo.kind === "synthetic_recorded_replay" && Boolean(demo.route);
}

/** Public footer that renders supplied metadata rather than manufacturing release facts. */
export function SiteFooter({
  onNavigate,
  productName = "Migration Control",
  links = [],
  demo,
  sourceRepoUrl,
  documentationUrl,
  className = "",
}: SiteFooterProps) {
  const replayAvailable = hasPublishedReplay(demo);
  const navigate = (event: MouseEvent<HTMLAnchorElement>, route: string, external = false) => {
    if (external || !onNavigate) return;
    event.preventDefault();
    onNavigate(route);
  };

  return (
    <footer role="contentinfo" className={`site-footer ${className}`.trim()}>
      <div className="site-footer__spectrum-bar" aria-hidden="true" />
      <div className="site-footer__container">
        <div className="site-footer__grid">
          <section className="site-footer__col" aria-labelledby="footer-product">
            <div className="site-footer__heading"><span className="site-footer__heading-accent site-footer__heading-accent--blue" /><span id="footer-product">{productName}</span></div>
            <p className="site-footer__text">A visual control surface for reviewing migration work. Public content is intentionally limited to supplied, owner-published information.</p>
            <span className="telemetry-tag"><PixelIcon name="shield-check" size="xs" color="google-blue" /><span>DATA-DRIVEN DISCLOSURE</span></span>
          </section>

          <section className="site-footer__col" aria-labelledby="footer-navigation">
            <div className="site-footer__heading"><span className="site-footer__heading-accent site-footer__heading-accent--yellow" /><span id="footer-navigation">Navigation</span></div>
            <ul className="site-footer__links">
              {links.map((link) => <li key={`${link.label}-${link.route}`}><a href={link.route} className="site-footer__link" target={link.isExternal ? "_blank" : undefined} rel={link.isExternal ? "noopener noreferrer" : undefined} onClick={(event) => navigate(event, link.route, link.isExternal)}><PixelIcon name="sparkle" size="xs" color="muted" /><span>{link.label}</span></a></li>)}
              {replayAvailable ? <li><a href={demo.route} className="site-footer__link" onClick={(event) => navigate(event, demo.route)}><PixelIcon name="play" size="xs" color="google-yellow" /><span>{demo.title}</span></a></li> : <li className="site-footer__text">No public replay has been supplied.</li>}
            </ul>
          </section>

          <section className="site-footer__col" aria-labelledby="footer-access">
            <div className="site-footer__heading"><span className="site-footer__heading-accent site-footer__heading-accent--green" /><span id="footer-access">Access</span></div>
            <p className="site-footer__text">Authentication availability, account identity, and any cloud connection are reported by the configured application. This page does not infer them.</p>
            {documentationUrl ? <a href={documentationUrl} className="site-footer__link" onClick={(event) => navigate(event, documentationUrl)}><span>Read the architecture notes →</span></a> : <p className="site-footer__text">Architecture notes have not been linked.</p>}
          </section>

          <section className="site-footer__col" aria-labelledby="footer-source">
            <div className="site-footer__heading"><span className="site-footer__heading-accent site-footer__heading-accent--red" /><span id="footer-source">Source</span></div>
            {sourceRepoUrl ? <a href={sourceRepoUrl} target="_blank" rel="noopener noreferrer" className="site-footer__link"><PixelIcon name="branch" size="xs" color="google-blue" /><span>Source repository</span></a> : <p className="site-footer__text">No source repository has been supplied.</p>}
            <div className="site-footer__disclosure-box"><strong>PUBLIC VIEW:</strong> shown values are supplied by the page owner. Missing values remain absent rather than being estimated.</div>
          </section>
        </div>
      </div>
    </footer>
  );
}
