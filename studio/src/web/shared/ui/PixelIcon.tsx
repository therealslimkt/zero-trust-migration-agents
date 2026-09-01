import type { SVGProps } from "react";
import { PIXEL_ICON_GRIDS, PIXEL_ICON_PATHS, type PixelIconName } from "../../assets/pixel/index";

export type PixelIconColor =
  | "google-blue"
  | "google-red"
  | "google-yellow"
  | "google-green"
  | "current"
  | "muted"
  | "secondary"
  | "white"
  | (string & {});

export type PixelIconSize = "xs" | "sm" | "md" | "lg" | "xl" | number;

export interface PixelIconProps extends Omit<SVGProps<SVGSVGElement>, "name" | "color" | "size"> {
  /** The registered name of the pixel art icon */
  name?: PixelIconName;
  /** Size variant or numerical pixel dimensions (default: 'sm' = 16px) */
  size?: PixelIconSize;
  /** Semantic Google colorway, text tone, or custom color */
  color?: PixelIconColor;
  /** Whether to project a chromatic accent glow */
  glow?: boolean;
  /** Optional custom SVG path string (defaults to registered name path) */
  path?: string;
  /** Pixel scaling factor multiplier (1x, 2x, 3x, 4x) */
  pixelScale?: 1 | 2 | 3 | 4;
  /** Accessible title for screen readers / hover tooltip */
  title?: string;
  /** Explicit ARIA label; when omitted, the icon is marked aria-hidden */
  ariaLabel?: string;
}

const PRESET_SIZES: Record<"xs" | "sm" | "md" | "lg" | "xl", number> = {
  xs: 12,
  sm: 16,
  md: 20,
  lg: 24,
  xl: 32,
};

const COLOR_CLASSES: Record<string, string> = {
  "google-blue": "pixel-icon--google-blue",
  "google-red": "pixel-icon--google-red",
  "google-yellow": "pixel-icon--google-yellow",
  "google-green": "pixel-icon--google-green",
  current: "pixel-icon--current",
  muted: "pixel-icon--muted",
  secondary: "pixel-icon--secondary",
  white: "pixel-icon--white",
};

/**
 * PixelIcon - Crisp, vector pixel-art icon renderer with integer grid alignment,
 * Google 4-color accent glows, and full WCAG accessibility.
 */
export function PixelIcon({
  name = "terminal",
  size = "sm",
  color = "current",
  glow = false,
  path,
  pixelScale,
  title,
  ariaLabel,
  className = "",
  style,
  ...svgProps
}: PixelIconProps) {
  const pathData = path || (name ? PIXEL_ICON_PATHS[name] : "");
  // Most icons are drawn on a 16x16 grid; denser motifs are authored at 32x32.
  const grid = (name && PIXEL_ICON_GRIDS[name]) || 16;
  const numericSize = typeof size === "number" ? size : PRESET_SIZES[size] || 16;
  const isNamedColor = color in COLOR_CLASSES;
  const colorClass = isNamedColor ? COLOR_CLASSES[color] : "";
  const customColorStyle = !isNamedColor && color ? { color } : undefined;

  const dimension = pixelScale ? grid * pixelScale : numericSize;
  const isAriaHidden = !ariaLabel && !title;

  return (
    <span
      className={[
        "pixel-icon",
        typeof size === "string" ? `pixel-icon--${size}` : "",
        colorClass,
        glow ? "pixel-icon--glow" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={{
        width: `${dimension}px`,
        height: `${dimension}px`,
        ...customColorStyle,
        ...style,
      }}
      role={isAriaHidden ? "presentation" : "img"}
      aria-label={ariaLabel || title}
      aria-hidden={isAriaHidden ? "true" : undefined}
    >
      <svg
        viewBox={`0 0 ${grid} ${grid}`}
        fill="currentColor"
        shapeRendering="crispEdges"
        xmlns="http://www.w3.org/2000/svg"
        {...svgProps}
      >
        {title ? <title>{title}</title> : null}
        {pathData ? <path d={pathData} /> : null}
      </svg>
    </span>
  );
}
