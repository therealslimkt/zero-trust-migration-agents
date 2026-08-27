/**
 * Mission-Control Visual System - Pixel Asset Registry
 * 
 * Crisp 16x16 pixel-art SVG path and geometry definitions for instant,
 * zero-network, zero-dependency rendering in PixelIcon.
 */

export const PIXEL_ICON_PATHS = {
  terminal:
    "M1 2h14v12H1V2zm1 1v10h12V3H2zm2 2h2v1H4V5zm2 1h2v1H6V6zm-2 1h2v1H4V7zm5 3h4v1H9v-1z",
  "shield-check":
    "M2 1h12v7c0 3-3 6-6 7-3-1-6-4-6-7V1zm1 1v6c0 2.5 2.5 5 5 5.8 2.5-.8 5-3.3 5-5.8V2H3zm8 3l-4 5-2-2 1-1 1 1 3-4 1 1z",
  radar:
    "M7 0h2v1H7V0zM3 1h2v1H3V1zm8 0h2v1h-2V1zM1 3h2v1H1V3zm12 0h2v1h-2V3zM0 7h1v2H0V7zm15 0h1v2h-1V7zM1 12h2v1H1v-1zm12 0h2v1h-2v-1zM3 14h2v1H3v-1zm8 0h2v1h-2v-1zM7 15h2v1H7v-1zM7 3h2v4h4v2H9v4H7V9H3V7h4V3zm1 3v2h2V6H8z",
  cpu:
    "M4 0h1v2H4V0zm7 0h1v2h-1V0zM0 4h2v1H0V4zm0 7h2v1H0v-1zm14-7h2v1h-2V4zm0 7h2v1h-2v-1zM4 14h1v2H4v-2zm7 0h1v2h-1v-2zM2 2h12v12H2V2zm1 1v10h10V3H3zm2 2h6v6H5V5zm1 1v4h4V6H6z",
  server:
    "M1 1h14v4H1V1zm1 1v2h12V2H2zm1 1h1v1H3V3zm2 0h1v1H5V3zm6 0h2v1h-2V3zM1 6h14v4H1V6zm1 1v2h12V7H2zm1 1h1v1H3V8zm2 0h1v1H5V8zm6 0h2v1h-2V8zM1 11h14v4H1v-4zm1 1v2h12v-2H2zm1 1h1v1H3v-1zm2 0h1v1H5v-1zm6 0h2v1h-2v-1z",
  sparkle:
    "M7 0h2v3H7V0zM7 13h2v3H7v-3zM0 7h3v2H0V7zm13 0h3v2h-3V7zm3-4h1v1h-1V3zm-1 1h1v1h-1V4zm-1 1h1v1h-1V5zM3 3h1v1H3V3zm1 1h1v1H4V4zm1 1h1v1H5V5zm6 6h1v1h-1v-1zm1 1h1v1h-1v-1zm1 1h1v1h-1v-1zM5 11h1v1H5v-1zm-1 1h1v1H4v-1zm-1 1h1v1H3v-1zM6 6h4v4H6V6z",
  bug:
    "M4 1h1v2H4V1zm7 0h1v2h-1V1zM5 3h6v2H5V3zm-3 3h2v1H2V6zm10 0h2v1h-2V6zM1 9h3v1H1V9zm11 0h3v1h-3V9zm1 3h2v1h-2v-1zM2 12h2v1H2v-1zm2-6h8v7H4V6zm2 2h4v4H6V8z",
  play:
    "M4 2h2v1H4V2zm0 1h3v1H4V3zm0 1h4v1H4V4zm0 1h5v1H4V5zm0 1h6v1H4V6zm0 1h7v2H4V7zm0 2h6v1H4V9zm0 1h5v1H4v-1zm0 1h4v1H4v-1zm0 1h3v1H4v-1zm0 1h2v1H4v-1z",
  rewind:
    "M7 2h1v12H7V2zm-1 2h1v8H6V4zm-1 1h1v6H5V5zm-1 1h1v4H4V6zm-1 1h1v2H3V7zm11-5h1v12h-1V2zm-1 2h1v8h-1V4zm-1 1h1v6h-1V5zm-1 1h1v4h-1V6zm-1 1h1v2h-1V7z",
  branch:
    "M2 1h3v3H2V1zm1 1v1h1V2H3zm0 2h1v8H3V4zm0 8h1v3H3v-3zm0 3H2v-3h1v3zm8-13h3v3h-3V2zm1 1v1h1V3h-1zm0 2h1v2h-1V5zm-1 3h2v1h-2V8zm-2 1h2v1H8V9zm-2 1h2v1H6v-1zm-2 1h2v1H4v-1zm7 0h3v3h-3v-3zm1 1v1h1v-1h-1z",
  satellite:
    "M0 0h4v2H0V0zm1 2h2v2H1V2zm5 1h1v1H6V3zm1 1h1v1H7V4zm1 1h1v1H8V5zm1 1h1v1H9V6zm-3 2h2v2H6V8zm6-7h4v2h-4V1zm0 2h1v2h-1V3zm2 0h1v2h-1V3zm-2 2h3v1h-3V5zm0 1h1v2h-1V6zm2 0h1v2h-1V6zm-2 2h4v2h-4V8zM1 11h2v4H1v-4zm2 0h2v1H3v-1zm2 2h2v1H5v-1zm-2 2h2v1H3v-1zm8-4h4v4h-4v-4z",
  "alert-triangle":
    "M7 1h2v2H7V1zm-1 2h4v2H6V3zm-1 2h6v2H5V5zm-1 2h8v2H4V7zm-1 2h10v2H3V9zm-1 2h12v2H2v-2zm-1 2h14v2H1v-2zm6-7h2v4H7V6zm0 5h2v2H7v-2z",
  sun:
    "M7 0h2v2H7V0zm0 14h2v2H7v-2zM0 7h2v2H0V7zm14 0h2v2h-2V7zM2 2h2v2H2V2zm10 0h2v2h-2V2zM2 12h2v2H2v-2zm10 0h2v2h-2v-2zM5 5h6v6H5V5zm1 1v4h4V6H6z",
  moon:
    "M6 1h4v1H6V1zM4 2h2v1H4V2zm6 0h2v2h-2V2zM3 3h1v2H3V3zm8 1h1v2h-1V4zM2 5h1v6H2V5zm9 1h1v4h-1V6zM3 11h1v2H3v-2zm8-1h1v2h-1v-2zm-5 4h4v1H6v-1zm4-1h2v-2h-2v2zm-6 0h2v1H4v-1z",
  "check-pixel":
    "M14 3h2v2h-2V3zm-2 2h2v2h-2V5zm-2 2h2v2h-2V7zm-2 2h2v2H8V9zM6 11h2v2H6v-2zM4 9h2v2H4V9zM2 7h2v2H2V7zm-2 0h2v2H0V7z",
  "cross-pixel":
    "M2 2h3v2H2V2zm9 0h3v2h-3V2zm-2 2h2v2H9V4zm-4 0h2v2H5V4zm2 2h2v2H7V6zm-2 2h2v2H5V8zm4 0h2v2H9V8zm-4 2h2v2H5v-2zm4 0h2v2H9v-2zm-6 2h3v2H3v-2zm8 0h3v2h-3v-2z",
  database:
    "M4 1h8v1H4V1zM2 2h2v1H2V2zm10 0h2v1h-2V2zM1 3h1v2H1V3zm14 0h1v2h-1V3zM2 5h2v1H2V5zm10 0h2v1h-2V5zm-8 1h8v1H4V6zm-3 1h1v2H1V7zm14 0h1v2h-1V7zM2 9h2v1H2V9zm10 0h2v1h-2V9zm-8 1h8v1H4v-1zm-3 1h1v2H1v-2zm14 0h1v2h-1v-2zm-13 2h2v1H2v-1zm10 0h2v1h-2v-1zm-8 1h8v1H4v-1z",
  lock:
    "M5 2h6v2H5V2zm-2 2h2v3H3V4zm8 0h2v3h-2V4zM1 7h14v8H1V7zm2 2v4h10V9H3zm4 1h2v1H7v-1zm0 1h2v1H7v-1z",
  key:
    "M10 1h4v1h-4V1zM9 2h1v4H9V2zm5 0h1v4h-1V2zm-4 4h4v1h-4V6zm-8 4h7v2H2v-2zm0-2h2v2H2V8zm3 4h2v2H5v-2zm-3 2h1v1H2v-1zm10-7h2v2h-2V7zm-1-4h2v2h-2V3z",
  activity:
    "M0 8h4v2H0V8zm3 0h2v-4H3v4zm2-4h2v10H5V4zm2 10h2v-7H7v7zm2-7h2v5H9V7zm2 5h2v-2h-2v2zm2-2h3v2h-3v-2z",
} as const;

export type PixelIconName = keyof typeof PIXEL_ICON_PATHS;

export const PIXEL_ICON_NAMES = Object.keys(PIXEL_ICON_PATHS) as PixelIconName[];
