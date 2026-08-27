import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";

export type BeaconStatus =
  | "active"
  | "standby"
  | "warning"
  | "critical"
  | "neutral"
  | "offline";

export type BeaconMode = "pulsing" | "ping" | "radar" | "steady";
export type BeaconSize = "xs" | "sm" | "md" | "lg";
export type BeaconShape = "circle" | "diamond" | "square";

export interface StatusBeaconProps {
  /** The operational status mapped to Google brand semantics */
  status: BeaconStatus;
  /** Textual status description for WCAG color-blind accessibility */
  label: string;
  /** Signal animation mode (default: 'pulsing') */
  mode?: BeaconMode;
  /** Visual dimension size (default: 'md') */
  size?: BeaconSize;
  /** Geometric pixel silhouette shape (default: 'circle') */
  shape?: BeaconShape;
  /** Optional secondary detail text or badge (e.g. "99.9% SLA", "12ms") */
  detail?: ReactNode;
  /** Whether to render the textual label visibly (always preserved in ARIA) */
  showLabel?: boolean;
  /** Whether to emit high-intensity neon glow bloom */
  pulseGlow?: boolean;
  /** Custom class for root container */
  className?: string;
}

const STATUS_DEFAULT_LABELS: Record<BeaconStatus, string> = {
  active: "Active",
  standby: "Standby",
  warning: "Warning",
  critical: "Critical",
  neutral: "Neutral",
  offline: "Offline",
};

/**
 * StatusBeacon - Mission-control telemetry signal indicator with concentric
 * radar pulses, Google 4-color status mappings, and accessible dual-signal readouts.
 */
export function StatusBeacon({
  status,
  label,
  mode = "pulsing",
  size = "md",
  shape = "circle",
  detail,
  showLabel = true,
  pulseGlow = true,
  className = "",
}: StatusBeaconProps) {
  const prefersReducedMotion = useReducedMotion();
  const displayLabel = label || STATUS_DEFAULT_LABELS[status];
  const isAnimated = !prefersReducedMotion && mode !== "steady" && status !== "offline";

  return (
    <span
      role="status"
      aria-live="polite"
      className={[
        "status-beacon",
        `status-beacon--${status}`,
        `status-beacon--${size}`,
        `status-beacon--${shape}`,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="status-beacon__signal-wrapper" aria-hidden="true">
        {/* Animated Concentric Outer Wave */}
        {isAnimated && (
          <motion.span
            className="status-beacon__ring"
            initial={{ width: "100%", height: "100%", opacity: 0.8 }}
            animate={
              mode === "ping"
                ? { width: ["100%", "280%"], height: ["100%", "280%"], opacity: [0.9, 0] }
                : mode === "radar"
                ? { width: ["100%", "360%"], height: ["100%", "360%"], opacity: [0.7, 0] }
                : { width: ["100%", "220%", "100%"], height: ["100%", "220%", "100%"], opacity: [0.6, 0, 0.6] }
            }
            transition={{
              duration: mode === "ping" ? 1.4 : mode === "radar" ? 2.2 : 1.8,
              repeat: Infinity,
              ease: "easeOut",
            }}
          />
        )}

        {/* Core Glowing Signal Center */}
        <motion.span
          className="status-beacon__core"
          animate={
            isAnimated && pulseGlow
              ? {
                  scale: [1, 1.15, 1],
                  opacity: [0.85, 1, 0.85],
                }
              : undefined
          }
          transition={
            isAnimated
              ? {
                  duration: 1.8,
                  repeat: Infinity,
                  ease: "easeInOut",
                }
              : undefined
          }
        />
      </span>

      {/* Screen Reader + Visual Text Readout */}
      {showLabel ? (
        <span className="status-beacon__text-group">
          <span className="status-beacon__label">{displayLabel}</span>
          {detail ? <span className="status-beacon__detail">[{detail}]</span> : null}
        </span>
      ) : (
        <span className="sr-only">
          {displayLabel}
          {detail ? ` - ${detail}` : ""}
        </span>
      )}
    </span>
  );
}
