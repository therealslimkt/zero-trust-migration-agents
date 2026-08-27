import { useState, useId, type ReactNode } from "react";
import { motion, AnimatePresence, useReducedMotion } from "motion/react";
import { PixelIcon } from "./PixelIcon";

export type TerminalVariant = "default" | "elevated" | "glass" | "bordered";
export type TerminalAccent = "google-blue" | "google-red" | "google-yellow" | "google-green" | "neutral";

export interface TerminalWindowProps {
  /** Main title displayed in the window chrome */
  title: string;
  /** Subtitle or breadcrumb path, e.g. "sys/agents/planner.ts" */
  breadcrumb?: string;
  /** Visual variant defining surface elevation and transparency */
  variant?: TerminalVariant;
  /** Accent color highlighting the window borders and active cues */
  accent?: TerminalAccent;
  /** Pixel icon name or custom element displayed before title */
  icon?: ReactNode;
  /** Right-aligned badge or pill indicator in header */
  badge?: ReactNode;
  /** Action buttons slot on the right side of the header */
  actions?: ReactNode;
  /** Bottom status bar or telemetry footer content */
  footer?: ReactNode;
  /** Extra slot inside header between title and actions */
  headerSlot?: ReactNode;
  /** Whether to render CRT scanline overlay */
  scanlines?: boolean;
  /** Whether to render corner bracket pixel HUD markers */
  cornerBrackets?: boolean;
  /** Whether to display Google-colored window control dots */
  showControls?: boolean;
  /** Controlled minimized state */
  isMinimized?: boolean;
  /** Default minimized state for uncontrolled mode */
  defaultMinimized?: boolean;
  /** Callback fired when the red close dot is clicked */
  onClose?: () => void;
  /** Callback fired when the yellow minimize dot is clicked */
  onMinimize?: (minimized: boolean) => void;
  /** Callback fired when the green maximize dot is clicked */
  onMaximize?: () => void;
  /** Custom max-height for the scrollable terminal body */
  maxHeight?: string | number;
  /** Custom min-height for the terminal body */
  minHeight?: string | number;
  /** Custom class for root container */
  className?: string;
  /** Custom class for scrollable body */
  bodyClassName?: string;
  /** Children content rendered inside terminal body */
  children?: ReactNode;
}

/**
 * TerminalWindow - Mission-control terminal chassis with Google traffic light
 * controls, telemetry metadata breadcrumbs, CRT scanlines, and fluid Motion transitions.
 */
export function TerminalWindow({
  title,
  breadcrumb,
  variant = "default",
  accent = "google-blue",
  icon = <PixelIcon name="terminal" size="xs" color={accent} glow />,
  badge,
  actions,
  footer,
  headerSlot,
  scanlines = false,
  cornerBrackets = false,
  showControls = true,
  isMinimized: controlledMinimized,
  defaultMinimized = false,
  onClose,
  onMinimize,
  onMaximize,
  maxHeight,
  minHeight,
  className = "",
  bodyClassName = "",
  children,
}: TerminalWindowProps) {
  const [internalMinimized, setInternalMinimized] = useState(defaultMinimized);
  const isMinimized = controlledMinimized !== undefined ? controlledMinimized : internalMinimized;
  const prefersReducedMotion = useReducedMotion();
  const titleId = useId();

  const handleToggleMinimize = () => {
    const nextState = !isMinimized;
    setInternalMinimized(nextState);
    onMinimize?.(nextState);
  };

  const formatDimension = (val?: string | number) =>
    typeof val === "number" ? `${val}px` : val;

  return (
    <section
      role="region"
      aria-labelledby={titleId}
      className={[
        "terminal-window",
        `terminal-window--${variant}`,
        cornerBrackets ? "pixel-frame--corner-brackets" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={
        accent !== "neutral"
          ? ({ "--pixel-accent-primary": `var(--${accent})` } as Record<string, string>)
          : undefined
      }
    >
      {/* Header Chrome */}
      <header
        className="terminal-window__header"
      >
        <div className="terminal-window__left">
          {showControls && (
            <div className="terminal-window__controls" aria-label="Window actions">
              <button
                type="button"
                className="terminal-window__dot terminal-window__dot--red"
                onClick={onClose}
                disabled={!onClose}
                aria-label={onClose ? "Close window" : "Close unavailable"}
                title="Close"
              />
              <button
                type="button"
                className="terminal-window__dot terminal-window__dot--yellow"
                onClick={handleToggleMinimize}
                aria-label={isMinimized ? "Expand window" : "Minimize window"}
                title={isMinimized ? "Expand" : "Minimize"}
              />
              <button
                type="button"
                className="terminal-window__dot terminal-window__dot--green"
                onClick={onMaximize}
                disabled={!onMaximize}
                aria-label={onMaximize ? "Maximize window" : "Maximize unavailable"}
                title="Maximize"
              />
            </div>
          )}

          <div className="terminal-window__title-group">
            {icon ? <span className="terminal-window__icon">{icon}</span> : null}
            <span id={titleId} className="terminal-window__title">
              {title}
            </span>
            {breadcrumb ? (
              <span className="terminal-window__breadcrumb" title={breadcrumb}>
                /{breadcrumb}
              </span>
            ) : null}
          </div>
        </div>

        {headerSlot}

        <div className="terminal-window__right">
          {badge}
          {actions}
        </div>
      </header>

      {/* Collapsible Body Content */}
      <AnimatePresence initial={false}>
        {!isMinimized && (
          <motion.div
            initial={prefersReducedMotion ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{
              duration: prefersReducedMotion ? 0 : 0.22,
              ease: [0.16, 1, 0.3, 1],
            }}
          >
            <div
              className={[
                "terminal-window__body",
                "pixel-scrollbar",
                scanlines ? "pixel-scanlines" : "",
                bodyClassName,
              ]
                .filter(Boolean)
                .join(" ")}
              style={{
                maxHeight: formatDimension(maxHeight),
                minHeight: formatDimension(minHeight),
                padding: "12px 14px",
              }}
            >
              {children}
            </div>

            {/* Optional Status/Telemetry Footer */}
            {footer && (
              <footer className="terminal-window__footer" aria-label="Terminal status bar">
                {footer}
              </footer>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
