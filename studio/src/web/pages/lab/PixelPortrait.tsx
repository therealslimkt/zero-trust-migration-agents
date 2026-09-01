import type { ReactElement } from "react";

// 16x16 pixel-art portraits drawn from character grids. No external assets:
// each glyph is a string map so the sprites stay diffable and theme-aware.

export type PortraitId =
  | "day-zero" | "the-heir" | "alias"
  | "atlas" | "prisma" | "vale" | "ledger" | "analyst";

const PALETTES: Record<string, Record<string, string>> = {
  villain: {
    o: "#ffd9d4", // outline — light, so the silhouette reads on any background
    s: "#c8323c", // shell
    m: "#e8555e", // mid
    h: "#ff8a7a", // hot
    g: "#fff3f1", // glint
    k: "#3d0f14", // void
  },
  hero: {
    o: "#0a1420", // outline
    b: "#184fa7", // deep blue
    m: "#8cb2f8", // blue
    g: "#fde193", // gold
    w: "#eaf1fa", // light
    n: "#82c996", // green
  },
};

// 16 rows x 16 cols. "." = transparent.
const GRIDS: Record<PortraitId, { pal: "villain" | "hero"; rows: string[] }> = {
  // ── VILLAINS ───────────────────────────────────────────────────────────
  // DAY ZERO — a torn calendar page; the date field is void.
  "day-zero": { pal: "villain", rows: [
    "................",
    "..oooooooooooo..",
    "..osssssssssso..",
    "..oshhhhhhhhso..",
    "..osssssssssso..",
    "..osokkkkkkoso..",
    "..osokkkkkkoso..",
    "..osokkggkkoso..",
    "..osokkggkkoso..",
    "..osokkkkkkoso..",
    "..osokkkkkkoso..",
    "..osssssssssso..",
    "..osmmosmmosmo..",
    "..osssssssssso..",
    "..oooooooooooo..",
    "................",
  ]},
  // THE HEIR — crowned bust whose lineage chain is broken.
  "the-heir": { pal: "villain", rows: [
    "................",
    "....o......o....",
    "...ogo....ogo...",
    "...ogooooogo....",
    "...oggggggggo...",
    "....oooooooo....",
    "....osssssso....",
    "...osmmmmmmso...",
    "...osmhhhhmso...",
    "...osmhggh mso..",
    "...osmmmmmmso...",
    "....osssssso....",
    "...osssssssso...",
    "..osso.oo.osso..",
    "..oo....o....oo.",
    "................",
  ]},
  // ALIAS — a mask; the true column hides behind it.
  "alias": { pal: "villain", rows: [
    "................",
    "...oooooooooo...",
    "..osssssssssso..",
    "..osmmmmmmmmso..",
    "..osmoommoomso..",
    "..osmokkmkkomso.",
    "..osmokgmgkomso.",
    "..osmoommoomso..",
    "..osmmmmmmmmso..",
    "..osmmhhhhmmso..",
    "...osmmmmmmso...",
    "....osssssso....",
    ".....oooooo.....",
    "......o..o......",
    "................",
    "................",
  ]},
  // ── AGENTS ─────────────────────────────────────────────────────────────
  // ATLAS — fleet marshal, visored helm.
  atlas: { pal: "hero", rows: [
    "................",
    "....oooooooo....",
    "...obbbbbbbbo...",
    "..obbmmmmmmbbo..",
    "..obmmmmmmmmbo..",
    "..obmoooooombo..",
    "..obmowwwwombo..",
    "..obmoooooombo..",
    "..obmmmmmmmmbo..",
    "...obmmmmmmbo...",
    "....obbbbbbo....",
    "...obggggggbo...",
    "..obbggggggbbo..",
    "..obo.oooo.obo..",
    "...o..o..o..o...",
    "................",
  ]},
  // PRISMA — transform architect, refracting prism.
  prisma: { pal: "hero", rows: [
    "................",
    ".......oo.......",
    "......obbo......",
    ".....obmmbo.....",
    "....obmmmmbo....",
    "...obmmwwmmbo...",
    "..obmmwwwwmmbo..",
    "..obmmwwwwmmbo..",
    "..obmmmmmmmmbo..",
    "..obggmmmmggbo..",
    "..obbbbbbbbbbo..",
    "...oooooooooo...",
    "....o.o..o.o....",
    "................",
    "................",
    "................",
  ]},
  // VALE — policy auditor, shield with a closed gate.
  vale: { pal: "hero", rows: [
    "................",
    "...oooooooooo...",
    "..obbbbbbbbbbo..",
    "..obnnnnnnnnbo..",
    "..obnoooooonbo..",
    "..obnowwwwonbo..",
    "..obnowoowonbo..",
    "..obnowwwwonbo..",
    "..obnoooooonbo..",
    "..obnnnnnnnnbo..",
    "...obnnnnnnbo...",
    "....obnnnnbo....",
    ".....obnnbo.....",
    "......obbo......",
    ".......oo.......",
    "................",
  ]},
  // LEDGER — reconciliation controller, balanced book.
  ledger: { pal: "hero", rows: [
    "................",
    "..oooooooooooo..",
    "..obbbbbbbbbbo..",
    "..obwwwwwwwwbo..",
    "..obwnnowwnnwbo.",
    "..obwwwowwwwbo..",
    "..obwnnowwnnwbo.",
    "..obwwwowwwwbo..",
    "..obwnnowwnnwbo.",
    "..obwwwowwwwbo..",
    "..obggggggggbo..",
    "..obbbbbbbbbbo..",
    "..oooooooooooo..",
    "................",
    "................",
    "................",
  ]},
  // ANALYST — frozen source analyst, single-turn lens.
  analyst: { pal: "hero", rows: [
    "................",
    "....oooooo......",
    "...obbbbbbo.....",
    "..obmmmmmmbo....",
    "..obmwwwwmbo....",
    "..obmwwwwmbo....",
    "..obmmmmmmbo....",
    "...obbbbbbo.....",
    "....oobboo......",
    "......obbo......",
    ".......obbo.....",
    "........obbo....",
    ".........obbo...",
    "..........obo...",
    "................",
    "................",
  ]},
};

export function PixelPortrait({ id, size = 96, title }: { id: PortraitId; size?: number; title?: string }) {
  const spec = GRIDS[id];
  const pal = PALETTES[spec.pal];
  const cells: ReactElement[] = [];
  spec.rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) {
      const ch = row[x];
      const fill = pal[ch];
      if (!fill) continue;
      cells.push(<rect key={`${x}-${y}`} x={x} y={y} width={1} height={1} fill={fill} />);
    }
  });
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      role="img"
      aria-label={title ?? id}
      style={{ imageRendering: "pixelated", shapeRendering: "crispEdges", display: "block" }}
    >
      {title ? <title>{title}</title> : null}
      {cells}
    </svg>
  );
}
