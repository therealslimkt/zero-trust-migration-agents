import { useState, useEffect } from "react";
import { motion, useReducedMotion } from "motion/react";
import { PixelIcon } from "./PixelIcon";

export type ThemeMode = "dark" | "light";
export type ThemeToggleVariant = "button" | "switch" | "segmented";
export type ThemeToggleSize = "sm" | "md" | "lg";
export type ThemeToggleAccent = "google-blue" | "google-yellow" | "rainbow";

export interface ThemeToggleProps {
  /** Controlled theme state */
  theme?: ThemeMode;
  /** Callback invoked on theme transition */
  onThemeChange?: (nextTheme: ThemeMode) => void;
  /** UI presentation variant */
  variant?: ThemeToggleVariant;
  /** Size multiplier */
  size?: ThemeToggleSize;
  /** Accent border or glow style */
  accent?: ThemeToggleAccent;
  /** Whether to show text label beside the toggle */
  showLabel?: boolean;
  /** Storage key to sync with localStorage when uncontrolled (default: "pixel-theme") */
  storageKey?: string;
  /** Custom class for root element */
  className?: string;
  /** Accessible label */
  ariaLabel?: string;
}

/**
 * ThemeToggle - Tactical dark/light mode switcher with pixel sun/moon iconography,
 * Google rainbow glow borders, and keyboard/screen-reader accessibility.
 */
export function ThemeToggle({
  theme: controlledTheme,
  onThemeChange,
  variant = "switch",
  size = "md",
  accent = "rainbow",
  showLabel = false,
  storageKey = "pixel-theme",
  className = "",
  ariaLabel = "Toggle color theme between dark and light",
}: ThemeToggleProps) {
  const [internalTheme, setInternalTheme] = useState<ThemeMode>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem(storageKey);
      if (stored === "dark" || stored === "light") return stored;
      const htmlTheme = document.documentElement.dataset.theme;
      if (htmlTheme === "dark" || htmlTheme === "light") return htmlTheme;
      if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
    }
    return "dark";
  });

  const currentTheme = controlledTheme !== undefined ? controlledTheme : internalTheme;
  const isDark = currentTheme === "dark";
  const prefersReducedMotion = useReducedMotion();

  const handleToggle = () => {
    const nextTheme: ThemeMode = isDark ? "light" : "dark";
    if (controlledTheme === undefined) {
      setInternalTheme(nextTheme);
      if (typeof window !== "undefined") {
        localStorage.setItem(storageKey, nextTheme);
        document.documentElement.dataset.theme = nextTheme;
      }
    }
    onThemeChange?.(nextTheme);
  };

  const handleSelectTheme = (selected: ThemeMode) => {
    if (selected === currentTheme) return;
    if (controlledTheme === undefined) {
      setInternalTheme(selected);
      if (typeof window !== "undefined") {
        localStorage.setItem(storageKey, selected);
        document.documentElement.dataset.theme = selected;
      }
    }
    onThemeChange?.(selected);
  };

  useEffect(() => {
    if (controlledTheme !== undefined && typeof window !== "undefined") {
      document.documentElement.dataset.theme = controlledTheme;
    }
  }, [controlledTheme]);

  const iconSize = size === "sm" ? "xs" : size === "lg" ? "md" : "sm";

  // 1. Segmented Control Variant
  if (variant === "segmented") {
    return (
      <div
        className={[
          "theme-toggle--segmented",
          `theme-toggle--${size}`,
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        role="radiogroup"
        aria-label={ariaLabel}
      >
        <button
          type="button"
          role="radio"
          aria-checked={isDark}
          className={`theme-toggle__segment ${isDark ? "theme-toggle__segment--active" : ""}`}
          onClick={() => handleSelectTheme("dark")}
        >
          <PixelIcon name="moon" size={iconSize} color={isDark ? "google-blue" : "muted"} glow={isDark} />
          <span>DARK</span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={!isDark}
          className={`theme-toggle__segment ${!isDark ? "theme-toggle__segment--active" : ""}`}
          onClick={() => handleSelectTheme("light")}
        >
          <PixelIcon name="sun" size={iconSize} color={!isDark ? "google-yellow" : "muted"} glow={!isDark} />
          <span>LIGHT</span>
        </button>
      </div>
    );
  }

  // 2. Sliding Switch Pill Variant
  if (variant === "switch") {
    return (
      <button
        type="button"
        role="switch"
        aria-checked={!isDark}
        aria-label={ariaLabel}
        className={[
          "theme-toggle",
          "theme-toggle--switch",
          `theme-toggle--${size}`,
          accent === "rainbow" ? "theme-toggle--rainbow" : "",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        onClick={handleToggle}
      >
        <motion.div
          className="theme-toggle__thumb"
          animate={{
            x: isDark ? "0%" : "100%",
          }}
          transition={{
            type: "spring",
            stiffness: prefersReducedMotion ? 1000 : 500,
            damping: prefersReducedMotion ? 100 : 30,
          }}
        >
          {isDark ? (
            <PixelIcon name="moon" size={iconSize} color="google-blue" glow />
          ) : (
            <PixelIcon name="sun" size={iconSize} color="google-yellow" glow />
          )}
        </motion.div>
        {showLabel && (
          <span className="theme-toggle__label text-xs uppercase font-mono font-semibold ml-2">
            {isDark ? "DARK" : "LIGHT"}
          </span>
        )}
      </button>
    );
  }

  // 3. Compact Icon Button Variant
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      className={[
        "theme-toggle",
        "theme-toggle--button",
        `theme-toggle--${size}`,
        accent === "rainbow" ? "theme-toggle--rainbow" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={handleToggle}
    >
      <motion.div
        key={currentTheme}
        initial={prefersReducedMotion ? false : { rotate: -45, scale: 0.85, opacity: 0 }}
        animate={{ rotate: 0, scale: 1, opacity: 1 }}
        exit={prefersReducedMotion ? undefined : { rotate: 45, scale: 0.85, opacity: 0 }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.18 }}
      >
        {isDark ? (
          <PixelIcon name="moon" size={iconSize} color="google-blue" glow />
        ) : (
          <PixelIcon name="sun" size={iconSize} color="google-yellow" glow />
        )}
      </motion.div>
      {showLabel && (
        <span className="text-xs uppercase font-mono font-semibold ml-2">
          {isDark ? "DARK" : "LIGHT"}
        </span>
      )}
    </button>
  );
}
