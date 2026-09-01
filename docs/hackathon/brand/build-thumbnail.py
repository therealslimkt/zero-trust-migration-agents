"""Keraun demo thumbnail: 1280x720, drawn rather than typeset.

Run from this directory:  python3 build-thumbnail.py
Then render the SVG at 2x and downscale to 1280x720 for upload.

The wordmark is stamped from 5x7 letterforms rather than set in a font, because
a mono face at 120px reads as large type and not as pixel art. The mark itself
is the real path from studio/src/web/shared/ui/BrandBolt.tsx, so the logo here
and the logo on the site cannot drift apart.
"""
import random

W, H = 1280, 720
BG, GRID = "#070b12", "#131c2b"
ORCHID, MAGENTA = "#e2b0e8", "#fa07c9"
VIOLET, DEEP = "#a86bff", "#6d28d9"
INK, FAINT = "#eef4fc", "#9fb2cc"

BOLT = ("M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287"
        "c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788"
        "L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471"
        "c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z")

# 5x7 letterforms, so the wordmark is pixel art rather than a font at a big size
FONT = {
 "K": ["#...#","#..#.","#.#..","##...","#.#..","#..#.","#...#"],
 "E": ["#####","#....","#....","####.","#....","#....","#####"],
 "R": ["####.","#...#","#...#","####.","#.#..","#..#.","#...#"],
 "A": [".###.","#...#","#...#","#####","#...#","#...#","#...#"],
 "U": ["#...#","#...#","#...#","#...#","#...#","#...#",".###."],
 "N": ["#...#","##..#","#.#.#","#.#.#","#..##","#...#","#...#"],
}

# A blocky bolt for the background streaks; the brand mark stays smooth.
PIXEL_BOLT = ["...##.","..###.",".###..","######","..###.",".###..","###...","##...."]

p = []
def rect(x, y, w, h, fill, op=1.0, extra=""):
    o = f' opacity="{op}"' if op != 1.0 else ""
    p.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="{fill}"{o}{extra}/>')

def stamp(grid, x, y, px, fill, op=1.0):
    for r, row in enumerate(grid):
        run = 0
        for c in range(len(row) + 1):
            on = c < len(row) and row[c] == "#"
            if on: run += 1
            elif run:
                rect(x + (c - run) * px, y + r * px, run * px, px, fill, op)
                run = 0

p.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')

# pixel grid wash
for gx in range(0, W, 16):
    for gy in range(0, H, 16):
        rect(gx, gy, 2, 2, GRID, 0.5)

# mini purple lightning streaks, kept off the centre so the mark stays clean
random.seed(7)
placed = []
for _ in range(150):
    if len(placed) >= 30: break
    x, y = random.randint(10, W - 90), random.randint(10, H - 110)
    px = random.choice([3, 4, 5, 6, 8])
    w, h = 6 * px, 8 * px
    cx_, cy_ = x + w / 2, y + h / 2
    if 470 < cx_ < 810 and 80 < cy_ < 330: continue      # the mark
    if 190 < cx_ < 1090 and 350 < cy_ < 640: continue    # the wordmark and both lines
    if any(abs(x - ox) < 90 and abs(y - oy) < 100 for ox, oy in placed): continue
    placed.append((x, y))
    colour = random.choice([VIOLET, DEEP, ORCHID, MAGENTA])
    stamp(PIXEL_BOLT, x, y, px, colour, random.choice([0.16, 0.22, 0.3, 0.4, 0.55]))

# corner brackets, for the record-sleeve framing
B, T, M = 74, 7, 34
for cx, cy, sx, sy in ((M, M, 1, 1), (W - M, M, -1, 1), (M, H - M, 1, -1), (W - M, H - M, -1, -1)):
    rect(min(cx, cx + sx * B), cy - (0 if sy > 0 else T), B, T, MAGENTA, 0.9)
    rect(cx - (0 if sx > 0 else T), min(cy, cy + sy * B), T, B, MAGENTA, 0.9)

# the mark
BOLT_SCALE = 4.2
BOLT_X = (W - 48 * BOLT_SCALE) / 2
p.append(f'<g transform="translate({BOLT_X:.0f} 96) scale({BOLT_SCALE})">'
         f'<path d="{BOLT}" fill="{ORCHID}" opacity=".5" transform="translate(2.6 2.2)"/>'
         f'<path d="{BOLT}" fill="{ORCHID}" stroke="{ORCHID}" stroke-width="1.25" stroke-linejoin="round"/>'
         f'<path d="{BOLT}" fill="{MAGENTA}" transform="translate(7.2 6.9) scale(.7)"/>'
         f'</g>')

# wordmark
PX, GAP = 17, 3
word = "KERAUN"
word_w = len(word) * (5 * PX) + (len(word) - 1) * GAP * PX
wx, wy = (W - word_w) / 2, 372
for i, ch in enumerate(word):
    x = wx + i * (5 * PX + GAP * PX)
    stamp(FONT[ch], x + 5, wy + 5, PX, DEEP, 0.55)   # drop shadow
    stamp(FONT[ch], x, wy, PX, INK)

p.append(f'<text x="{W/2}" y="{wy + 7 * PX + 62}" text-anchor="middle" font-size="34" font-weight="700" '
         f'letter-spacing="6.5" fill="{ORCHID}" font-family="ui-monospace, monospace">'
         f'FREE YOUR DATA WITHOUT THE CHARGE</text>')
p.append(f'<text x="{W/2}" y="{wy + 7 * PX + 104}" text-anchor="middle" font-size="21" '
         f'letter-spacing="4" fill="{FAINT}" font-family="ui-monospace, monospace">'
         f'OPEN SOURCE  ·  LEGACY ERP TO BIGQUERY  ·  keraun.dev</text>')

# scanlines
for y in range(0, H, 4):
    rect(0, y, W, 1, "#000000", 0.16)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
       f'shape-rendering="crispEdges">\n' + "\n".join(p) + "\n</svg>\n")
open("keraun-demo-thumbnail.svg", "w").write(svg)
print("wrote keraun-demo-thumbnail.svg —", len(svg), "bytes,", len(placed), "background streaks")
