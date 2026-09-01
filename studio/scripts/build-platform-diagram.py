import math
from pathlib import Path

sprite = Path("public/pixel-icons/pixel-icons.svg").read_text()
ICONS = sprite[sprite.index(">", sprite.index("<svg")) + 1: sprite.rindex("</svg>")].strip()
G = Path("src/web/assets/sprites/go-gopher.svg").read_text()
GOPHER = G[G.index(">", G.index("<svg")) + 1: G.rindex("</svg>")].strip()
BOLT = "M25.946 44.938c-.664.845-2.021.375-2.021-.698V33.937a2.26 2.26 0 0 0-2.262-2.262H10.287c-.92 0-1.456-1.04-.92-1.788l7.48-10.471c1.07-1.497 0-3.578-1.842-3.578H1.237c-.92 0-1.456-1.04-.92-1.788L10.013.474c.214-.297.556-.474.92-.474h28.894c.92 0 1.456 1.04.92 1.788l-7.48 10.471c-1.07 1.498 0 3.579 1.842 3.579h11.377c.943 0 1.473 1.088.89 1.83L25.947 44.94z"

INK, DIM, FAINT = "var(--dg-ink)", "var(--dg-dim)", "var(--dg-faint)"
PANEL, LINE = "var(--dg-panel)", "var(--dg-line)"
BLUE, GREEN, GOLD, RED, GO = ("var(--dg-blue)", "var(--dg-green)", "var(--dg-gold)",
                              "var(--dg-red)", "var(--dg-go)")
p = []
def esc(t): return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def node(x, y, icon, label, sub=None, accent=BLUE, r=30, size=None):
    """An icon disc with its name beneath. No container, no rectangle."""
    p.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{PANEL}" stroke="{accent}" stroke-width="2.5"/>')
    s = size or int(r * 1.05)
    p.append(f'<use fill="currentColor" href="#pixel-{icon}" x="{x-s//2}" y="{y-s//2}" '
             f'width="{s}" height="{s}" color="{accent}"/>')
    p.append(f'<text x="{x}" y="{y+r+24}" font-size="18" font-weight="700" fill="{INK}" '
             f'text-anchor="middle">{esc(label)}</text>')
    if sub:
        for i, line in enumerate(sub if isinstance(sub, list) else [sub]):
            p.append(f'<text x="{x}" y="{y+r+44+i*18}" font-size="15" fill="{FAINT}" '
                     f'text-anchor="middle">{esc(line)}</text>')

def curve(x1, y1, x2, y2, bow=0.28, accent=BLUE, label=None, flow=True, dash="10 16", head=True):
    """A bezier rail with a travelling dash, so the direction of flow is visible."""
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = mx - dy * bow, my + dx * bow
    d = f"M{x1} {y1} Q{cx:.0f} {cy:.0f} {x2} {y2}"
    p.append(f'<path d="{d}" stroke="{LINE}" stroke-width="2.5" fill="none"/>')
    if flow:
        p.append(f'<path class="dg-flow" d="{d}" stroke="{accent}" stroke-width="2.5" fill="none" '
                 f'stroke-dasharray="{dash}" stroke-linecap="round"/>')
    ang = math.atan2(y2 - cy, x2 - cx)
    ax, ay = x2 - 13 * math.cos(ang), y2 - 13 * math.sin(ang)
    px_, py_ = -math.sin(ang) * 7, math.cos(ang) * 7
    if head:
        p.append(f'<polygon points="{x2:.0f},{y2:.0f} {ax+px_:.0f},{ay+py_:.0f} {ax-px_:.0f},{ay-py_:.0f}" fill="{accent}"/>')
    if label:
        p.append(f'<text x="{cx:.0f}" y="{cy-18:.0f}" font-size="14" fill="{FAINT}" '
                 f'text-anchor="middle">{esc(label)}</text>')
    return d


def region(x, y, w, h, label, sub, accent, dashed=False):
    """A soft field, not a container: no fill weight, label sits outside the flow."""
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="26" fill="{accent}" opacity="0.045"/>')
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="26" fill="none" stroke="{accent}" '
             f'stroke-width="2"{" stroke-dasharray=\"10 8\"" if dashed else ""} opacity="0.55"/>')
    p.append(f'<text x="{x+26}" y="{y+34}" font-size="18" font-weight="700" fill="{accent}" letter-spacing="1.8">{esc(label)}</text>')
    if sub:
        p.append(f'<text x="{x+26}" y="{y+56}" font-size="15" fill="{FAINT}">{esc(sub)}</text>')

def packets(d, accent, count=3, dur=2.8, size=9, kind="byte"):
    """Send discrete things along a path so a lane reads as traffic.

    On the source side these are bytes leaving a sealed emulator; past the
    boundary they are records that have already been decoded and checked.
    """
    half = size / 2
    for i in range(count):
        begin = f"{(dur / count) * i:.2f}s"
        body = (f'<circle r="{half:.1f}" fill="{accent}"/>' if kind == "byte" else
                f'<rect x="{-half:.1f}" y="{-half:.1f}" width="{size}" height="{size}" rx="2" '
                f'fill="{accent}" stroke="{PANEL}" stroke-width="1.5"/>')
        p.append(f'<g class="dg-packets">{body}'
                 f'<animateMotion dur="{dur}s" begin="{begin}" repeatCount="indefinite" '
                 f'path="{d}" keyPoints="0;1" keyTimes="0;1" calcMode="linear"/></g>')


def pulse(x, y, r, accent, dur=2.4):
    """A ring leaving a node: this one is working right now."""
    p.append(f'<circle class="dg-pulse" cx="{x}" cy="{y}" r="{r}" fill="none" '
             f'stroke="{accent}" stroke-width="2.5">'
             f'<animate attributeName="r" values="{r};{r+26}" dur="{dur}s" repeatCount="indefinite"/>'
             f'<animate attributeName="opacity" values="0.7;0" dur="{dur}s" repeatCount="indefinite"/>'
             f'</circle>')


def note(x, y, t, c=DIM, size=15, anchor="start", weight="400", style=""):
    p.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{c}" '
             f'text-anchor="{anchor}"{style}>{esc(t)}</text>')

W, H = 2400, 1280
p.append(f'<g transform="translate(44 26) scale(0.9)">'
         f'<path d="{BOLT}" transform="translate(1.6 1.4)" fill="#e2b0e8" opacity="0.68"/>'
         f'<path d="{BOLT}" fill="#e2b0e8" stroke="#e2b0e8" stroke-width="1.25" stroke-linejoin="round"/>'
         f'<path d="{BOLT}" transform="translate(7.2 6.9) scale(0.7)" fill="#fa07c9"/></g>')
p.append(f'<text x="112" y="62" font-size="36" font-weight="700" fill="{INK}" letter-spacing="2.5">KERAUN</text>')
note(292, 62, "how a legacy record becomes a governed warehouse row", FAINT, 17)
note(2356, 62, "google cloud · ztm-agent-9049c3", FAINT, 13, "end")

# ── the sealed perimeter ────────────────────────────────────────────────
region(50, 116, 600, 620, "SEALED PERIMETER", "gVisor · internal-only network · no external IP", RED, dashed=True)
node(170, 260, "db2", "JD Edwards", "IBM Db2 for i", BLUE, 30)
node(170, 420, "database", "Dynamics AX", "SQL Server", BLUE, 30)
node(170, 580, "database", "Oracle EBS", "Oracle 19c", BLUE, 30)
node(500, 420, "lock", "Query runner", ["the only container", "allowed to ask"], GREEN, 34)
pulse(500, 420, 34, GREEN, 2.6)
for sy in (260, 420, 580):
    # Raw bytes leaving a sealed emulator, one lane per cartridge.
    packets(curve(206, sy, 466, 420, 0.10 if sy == 420 else 0.16, BLUE, flow=True),
            BLUE, count=4, dur=2.6, size=8, kind="byte")
node(500, 620, "cpu", "Gemma 2", ["reviews at the edge", "before anything leaves"], GOLD, 26)
curve(500, 586, 500, 458, -0.12, GOLD, flow=True)

# ── the trust boundary ──────────────────────────────────────────────────
p.append(f'<path d="M700 120 L700 736" stroke="{RED}" stroke-width="2.5" stroke-dasharray="9 7" opacity="0.8"/>')
note(700, 108, "TRUST BOUNDARY", RED, 15, "middle", "700")
note(700, 392, "sanitized artifacts only", RED, 14, "middle")
note(700, 752, "counts, digests and schema cross.", FAINT, 14, "middle")
note(700, 770, "raw rows, credentials and connection strings do not.", FAINT, 14, "middle")

# ── the control plane ───────────────────────────────────────────────────
p.append(f'<g transform="translate(880 300) scale(1.55)">{GOPHER}</g>')
note(925, 150, "GO CONTROL PLANE", GO, 19, "middle", "700")
note(925, 172, "the only source of truth", FAINT, 15, "middle")
packets(curve(534, 420, 866, 400, 0.06, RED), RED, count=3, dur=3.0, size=10, kind="frame")
for i, (x, y, ic, lb) in enumerate([(806, 208, "server", "three doors"),
                                    (1060, 250, "branch", "state machine"),
                                    (790, 560, "terminal", "frame admission"),
                                    (1060, 560, "database", "durable state")]):
    node(x, y, ic, lb, None, GO, 24, 20)
    curve(x + (28 if x < 925 else -28), y + (28 if y < 400 else -28),
          925 + (-40 if x < 925 else 40), 300 if y < 400 else 452,
          0.10, GO, flow=False, head=False)
note(925, 700, "every frame the browser sees was admitted here first", FAINT, 14, "middle")

# ── the fleet decides ───────────────────────────────────────────────────
region(1220, 116, 560, 620, "THE FLEET DECIDES", "reasoning on Vertex AI, bounded by code", BLUE)
node(1360, 250, "gemini", "PRISMA", ["plans on gemini-3.5-flash", "rename · cast · drop only"], BLUE, 32)
node(1640, 250, "shield-check", "VALE", ["certifies or rejects;", "cannot widen authority"], GREEN, 32)
node(1500, 500, "key", "THE STEWARD", ["one irreversible decision,", "bound to an exact digest"], GOLD, 34)
curve(1392, 282, 1608, 282, 0.30, BLUE)
note(1500, 196, "a closed declarative contract", FAINT, 14, "middle")
curve(1640, 282, 1534, 468, 0.16, GREEN)
curve(1360, 282, 1466, 468, -0.16, BLUE, flow=False)
packets(curve(985, 400, 1328, 250, 0.10, GO), GO, count=3, dur=2.8, size=10, kind="frame")
note(1150, 392, "typed task envelope", FAINT, 14, "middle")
note(1500, 640, "a stale digest is refused, never overridden", RED, 14, "middle")

# ── execution ───────────────────────────────────────────────────────────
region(1830, 116, 526, 620, "TRUSTED EXECUTION", "only reachable after approval", GREEN)
node(1960, 250, "apache-beam", "Apache Beam", ["2.75.0 · DirectRunner", "code we own, not the model"], GREEN, 32)
node(2230, 400, "bigquery", "BigQuery", ["explicit schema,", "never autodetect"], GREEN, 32)
node(1960, 560, "check-pixel", "LEDGER", ["read = accepted + rejected", "or completion is blocked"], GREEN, 30)
packets(curve(1534, 468, 1928, 282, -0.14, GOLD), GOLD, count=3, dur=2.6, size=10, kind="frame")
note(1740, 452, "approved plan", FAINT, 14, "middle")
packets(curve(1992, 282, 2200, 372, 0.18, GREEN), GREEN, count=3, dur=2.4, size=10, kind="frame")
note(2130, 268, "typed rows", FAINT, 14, "middle")
curve(2202, 428, 1990, 534, 0.14, GREEN)
note(2093, 700, "500 read · 498 accepted · 2 rejected · MATCHED", GREEN, 12.5, "middle", "700")

# ── the fleet roster, as a legend rather than a grid ────────────────────
note(50, 872, "THE FLEET", INK, 19, weight="700")
note(160, 872, "every agent carries a typed envelope, a scoped identity, an allowlisted tool set and an evidence obligation", FAINT, 12.5)
roster = [("satellite", "ATLAS", "delegates; cannot approve or execute", GO),
          ("lock", "JETTY", "guards the edge; holds no cloud keys", GOLD),
          ("db2", "RUNE", "decodes JDE EBCDIC and packed decimal", BLUE),
          ("sqlserver", "AXIOM", "resolves AX table inheritance", BLUE),
          ("oracle", "FLEX", "names EBS descriptive flexfields", BLUE),
          ("jdbc-jar", "MAVEN", "fingerprints drivers; never runs the JAR", BLUE),
          ("gemini", "PRISMA", "proposes plans; emits no code", BLUE),
          ("shield-check", "VALE", "rejects or certifies", GREEN),
          ("key", "THE STEWARD", "one irreversible human decision", GOLD),
          ("apache-beam", "FLOW", "launches allowlisted transforms", GREEN),
          ("check-pixel", "LEDGER", "proves destination matches input", GREEN),
          ("radar", "SCOUT", "reads catalog intent; bypasses no query", BLUE)]
for i, (ic, nm, duty, c) in enumerate(roster):
    col, row = i % 3, i // 3
    x, y = 60 + col * 790, 918 + row * 62
    p.append(f'<use fill="currentColor" href="#pixel-{ic}" x="{x}" y="{y-14}" width="19" height="19" color="{c}"/>')
    p.append(f'<text x="{x+30}" y="{y}" font-size="16" font-weight="700" fill="{c}" letter-spacing="0.6">{esc(nm)}</text>')
    p.append(f'<text x="{x+30+len(nm)*9.6+16}" y="{y}" font-size="15" fill="{DIM}">{esc(duty)}</text>')
note(60, 1188, "reasoning is an agent node · predictable work is a function node · no agent may approve its own work", FAINT, 12)
note(60, 1236, "VERIFIED 2026-09-01   ·   Gemini 3.5 Flash on Vertex AI   ·   Beam 2.75.0 over 500 sealed records   ·   reconciled in BigQuery", GREEN, 12.5, weight="700")

svg = f'''<svg font-family="var(--font-mono-tactical)" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Keraun platform architecture">
<defs>{ICONS}</defs>
<style>
  .dg-flow {{ animation: dg-travel 1.4s linear infinite; }}
  @keyframes dg-travel {{ to {{ stroke-dashoffset: -26; }} }}
  @media (prefers-reduced-motion: reduce) {{
    /* animateMotion cannot be paused from CSS, so the moving parts are removed. */
    .dg-packets, .dg-pulse {{ display: none; }}
  }}
  @media (prefers-reduced-motion: reduce) {{ .dg-flow {{ animation: none; opacity: .75; }} }}
</style>
<rect width="{W}" height="{H}" fill="var(--dg-bg)"/>
{chr(10).join(p)}
</svg>'''
Path("src/web/assets/architecture/platform.svg").write_text(svg)
print("platform:", len(svg), "bytes")
