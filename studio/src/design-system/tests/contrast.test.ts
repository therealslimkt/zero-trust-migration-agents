import assert from "node:assert/strict";
import { test } from "vitest";

function luminance(hex: string): number {
  const channels = hex.slice(1).match(/../g)?.map((value) => Number.parseInt(value, 16) / 255);
  if (!channels || channels.length !== 3) throw new Error(`Invalid six-digit hex color: ${hex}`);
  const [red, green, blue] = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4) as [number, number, number];
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function contrast(first: string, second: string): number {
  const firstLuminance = luminance(first);
  const secondLuminance = luminance(second);
  return (Math.max(firstLuminance, secondLuminance) + 0.05) / (Math.min(firstLuminance, secondLuminance) + 0.05);
}

test("initial semantic foreground/background pairs meet WCAG AA normal-text contrast", () => {
  const pairs: ReadonlyArray<readonly [string, string]> = [
    ["#3b79a6", "#fffdf5"],
    ["#b43a36", "#fffdf5"],
    ["#f6e4a6", "#2b211d"],
    ["#a8c98a", "#2b211d"],
    ["#79acd0", "#2b211d"],
  ];
  for (const [foreground, background] of pairs) {
    assert.ok(contrast(foreground, background) >= 4.5, `${foreground} on ${background} must meet 4.5:1`);
  }
});
