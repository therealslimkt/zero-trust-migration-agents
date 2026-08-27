import type { ReactNode, MouseEvent } from "react";
import { motion, useReducedMotion } from "motion/react";
import { PixelIcon } from "./PixelIcon";

export type ReplayMode = "live" | "replay" | "recording" | "scrubbing" | "checkpoint" | "diff";
export type ReplayBadgeSize = "sm" | "md" | "lg";

export interface ReplayBadgeProps {
  /** Operational playback mode */
  mode?: ReplayMode;
  /** ISO or formatted timestamp string, e.g. "14:22:08.104" */
  timestamp?: string;
  /** Current frame index or step counter */
  step?: number;
  /** Total available frames/steps */
  totalSteps?: number;
  /** Playback velocity multiplier, e.g. "1x", "2x", "10x" */
  speed?: string;
  /** Whether playback is actively running */
  isPlaying?: boolean;
  /** Optional custom detail or revision ID string (e.g. "v1.4.2-rev8") */
  detail?: ReactNode;
  /** Badge size (default: 'md') */
  size?: ReplayBadgeSize;
  /** Whether the badge behaves as an interactive button */
  interactive?: boolean;
  /** Callback fired on click when interactive */
  onClick?: (event: MouseEvent<HTMLElement>) => void;
  /** Callback to step forward or toggle playback */
  onTogglePlay?: () => void;
  /** Custom root className */
  className?: string;
}

/**
 * ReplayBadge - Telemetry timestamp badge for historical audit replays,
 * live flight recorders, checkpoint verifications, and event-sourcing playbacks.
 */
export function ReplayBadge({
  mode = "live",
  timestamp,
  step,
  totalSteps,
  speed,
  isPlaying,
  detail,
  size = "md",
  interactive = false,
  onClick,
  onTogglePlay,
  className = "",
}: ReplayBadgeProps) {
  const prefersReducedMotion = useReducedMotion();

  const isLive = mode === "live";
  const isRecording = mode === "recording";

  const getModeIcon = () => {
    switch (mode) {
      case "live":
        return <PixelIcon name="satellite" size="xs" color="google-green" glow />;
      case "recording":
        return <PixelIcon name="activity" size="xs" color="google-red" glow />;
      case "replay":
        return isPlaying ? (
          <PixelIcon name="play" size="xs" color="google-yellow" glow />
        ) : (
          <PixelIcon name="rewind" size="xs" color="google-yellow" />
        );
      case "checkpoint":
        return <PixelIcon name="shield-check" size="xs" color="google-blue" glow />;
      case "scrubbing":
        return <PixelIcon name="radar" size="xs" color="google-blue" />;
      case "diff":
        return <PixelIcon name="branch" size="xs" color="google-blue" />;
      default:
        return null;
    }
  };

  const getModeLabel = () => {
    switch (mode) {
      case "live":
        return "LIVE";
      case "recording":
        return "REC";
      case "replay":
        return "REPLAY";
      case "checkpoint":
        return "CHECKPOINT";
      case "scrubbing":
        return "SEEK";
      case "diff":
        return "DIFF";
      default:
        return mode;
    }
  };

  const ariaDescription = [
    `Playback mode: ${getModeLabel()}`,
    timestamp ? `Timestamp: ${timestamp}` : null,
    step !== undefined ? `Step ${step}${totalSteps ? ` of ${totalSteps}` : ""}` : null,
    speed ? `Speed: ${speed}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  const content = (
    <>
      {/* Live / Recording Pulsing Indicator */}
      {(isLive || isRecording) && (
        <motion.span
          className="replay-badge__indicator"
          aria-hidden="true"
          animate={
            !prefersReducedMotion
              ? {
                  opacity: [1, 0.35, 1],
                  scale: [1, 1.25, 1],
                }
              : undefined
          }
          transition={
            !prefersReducedMotion
              ? {
                  duration: isRecording ? 1.0 : 1.6,
                  repeat: Infinity,
                  ease: "easeInOut",
                }
              : undefined
          }
        />
      )}

      {/* Mode Icon */}
      {getModeIcon()}

      {/* Mode Text Tag */}
      <span className="replay-badge__mode-tag">{getModeLabel()}</span>

      {/* Timestamp */}
      {timestamp && (
        <span className="replay-badge__timestamp" title={`Recorded time: ${timestamp}`}>
          {timestamp}
        </span>
      )}

      {/* Step Counter */}
      {step !== undefined && (
        <span className="replay-badge__step-counter">
          STEP {step}
          {totalSteps !== undefined ? `/${totalSteps}` : ""}
        </span>
      )}

      {/* Speed Rate Indicator */}
      {speed && (
        <span className="replay-badge__speed" title={`Playback velocity ${speed}`}>
          {speed}
        </span>
      )}

      {/* Optional Metadata Detail */}
      {detail && <span className="text-muted text-2xs">{detail}</span>}
    </>
  );

  const containerClasses = [
    "replay-badge",
    `replay-badge--${mode}`,
    `replay-badge--${size}`,
    interactive || onClick ? "replay-badge--interactive" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  if (interactive || onClick || onTogglePlay) {
    return (
      <button
        type="button"
        className={containerClasses}
        onClick={(e) => {
          onTogglePlay?.();
          onClick?.(e);
        }}
        aria-label={ariaDescription}
      >
        {content}
      </button>
    );
  }

  return (
    <span className={containerClasses} role="status" aria-label={ariaDescription}>
      {content}
    </span>
  );
}
