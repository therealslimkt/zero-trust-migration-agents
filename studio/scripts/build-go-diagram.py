from pathlib import Path
import math

sprite = Path("public/pixel-icons/pixel-icons.svg").read_text()
ICONS = sprite[sprite.index(">", sprite.index("<svg")) + 1: sprite.rindex("</svg>")].strip()
G = Path("src/web/assets/sprites/go-gopher.svg").read_text()
GOPHER = G[G.index(">", G.index("<svg")) + 1: G.rindex("</svg>")].strip()

INK, DIM, FAINT = "var(--dg-ink)", "var(--dg-dim)", "var(--dg-faint)"
PANEL, LINE = "var(--dg-panel)", "var(--dg-line)"
BLUE, GREEN, GOLD, RED, GO = ("var(--dg-blue)", "var(--dg-green)", "var(--dg-gold)",
                              "var(--dg-red)", "var(--dg-go)")
p = []
def esc(t): return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def node(x, y, icon, label, sub=None, accent=GO, r=30, size=None):
    p.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{PANEL}" stroke="{accent}" stroke-width="2.5"/>')
    s = size or int(r * 1.05)
    p.append(f'<use fill="currentColor" href="#pixel-{icon}" x="{x-s//2}" y="{y-s//2}" width="{s}" height="{s}" color="{accent}"/>')
    p.append(f'<text x="{x}" y="{y+r+24}" font-size="15" font-weight="700" fill="{INK}" text-anchor="middle">{esc(label)}</text>')
    for i, line in enumerate(sub or []):
        p.append(f'<text x="{x}" y="{y+r+44+i*18}" font-size="12.5" fill="{FAINT}" text-anchor="middle">{esc(line)}</text>')

def curve(x1, y1, x2, y2, bow=0.24, accent=GO, flow=True, head=True, dash="10 16"):
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = mx - dy * bow, my + dx * bow
    d = f"M{x1} {y1} Q{cx:.0f} {cy:.0f} {x2} {y2}"
    p.append(f'<path d="{d}" stroke="{LINE}" stroke-width="2.5" fill="none"/>')
    if flow:
        p.append(f'<path class="dg-flow" d="{d}" stroke="{accent}" stroke-width="2.5" fill="none" stroke-dasharray="{dash}" stroke-linecap="round"/>')
    if head:
        ang = math.atan2(y2 - cy, x2 - cx)
        ax, ay = x2 - 13 * math.cos(ang), y2 - 13 * math.sin(ang)
        px_, py_ = -math.sin(ang) * 7, math.cos(ang) * 7
        p.append(f'<polygon points="{x2:.0f},{y2:.0f} {ax+px_:.0f},{ay+py_:.0f} {ax-px_:.0f},{ay-py_:.0f}" fill="{accent}"/>')

def note(x, y, t, c=DIM, size=12.5, anchor="start", weight="400"):
    p.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{c}" text-anchor="{anchor}">{esc(t)}</text>')

def region(x, y, w, h, label, sub, accent):
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="26" fill="{accent}" opacity="0.045"/>')
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="26" fill="none" stroke="{accent}" stroke-width="2" opacity="0.5"/>')
    p.append(f'<text x="{x+26}" y="{y+34}" font-size="15" font-weight="700" fill="{accent}" letter-spacing="1.8">{esc(label)}</text>')
    if sub: p.append(f'<text x="{x+26}" y="{y+56}" font-size="12.5" fill="{FAINT}">{esc(sub)}</text>')

W, H = 2400, 1080
p.append(f'<g transform="translate(44 20) scale(1.15)">{GOPHER}</g>')
p.append(f'<text x="132" y="62" font-size="28" font-weight="700" fill="{INK}" letter-spacing="2">GO CONTROL PLANE</text>')
note(560, 62, "studio-backend/ · deterministic · zero LLM", FAINT, 15)
note(2356, 62, "the browser reads it but never owns it", GO, 13, "end")

# ── three doors, each with its own credential ───────────────────────────
region(50, 130, 520, 560, "THREE DOORS", "loopback only · Origin refused", GO)
for i, (ic, lb, sub, c) in enumerate([
        ("terminal", "/internal/v1/terminal", ["producer token", "frames in"], GO),
        ("branch", "/internal/v1/orchestration", ["orchestrator token", "state transitions"], GO),
        ("identity-platform", "/api/web/v1/…", ["Identity Platform", "the browser's door"], BLUE)]):
    node(190, 250 + i * 152, ic, lb, sub, c, 28)

# ── admission ───────────────────────────────────────────────────────────
node(760, 320, "shield-check", "Admission", ["schema · enum · ordering", "credentials suppressed"], GREEN, 34)
note(760, 440, "a frame is data, never a command", RED, 12.5, "middle")
for i in range(3):
    curve(228, 250 + i * 152, 726, 320, 0.06, GO, head=False)

# ── the state machine as a ring ─────────────────────────────────────────
region(1080, 130, 700, 560, "FROZEN STATE MACHINE", "each step names the evidence it requires", GO)
STATES = ["created", "inventorying", "redacting", "planning", "awaiting_approval",
          "approved", "executing", "verifying", "completed"]
cx, cy, rad = 1430, 420, 185
pts = []
for i, st in enumerate(STATES):
    a = -math.pi / 2 + i * (2 * math.pi / len(STATES))
    x, y = cx + rad * math.cos(a), cy + rad * math.sin(a)
    pts.append((x, y))
    gate = st == "awaiting_approval"
    done = st == "completed"
    c = GOLD if gate else (GREEN if done else GO)
    p.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="11" fill="{PANEL}" stroke="{c}" stroke-width="2.5"/>')
    ta = "middle"
    ox, oy = 0, -20 if y < cy else 26
    if abs(x - cx) > rad * 0.75:
        ta, ox, oy = ("start" if x > cx else "end"), (20 if x > cx else -20), 5
    p.append(f'<text x="{x+ox:.0f}" y="{y+oy:.0f}" font-size="12.5" font-weight="{"700" if gate or done else "400"}" '
             f'fill="{c if (gate or done) else DIM}" text-anchor="{ta}">{esc(st)}</text>')
for i in range(len(pts) - 1):
    x1, y1 = pts[i]; x2, y2 = pts[i + 1]
    curve(x1, y1, x2, y2, 0.06, GO, flow=(i == 4), head=True, dash="6 10")
p.append(f'<use fill="currentColor" href="#pixel-key" x="{cx-16}" y="{cy-30}" width="32" height="32" color="{GOLD}"/>')
note(cx, cy + 16, "one human decision", GOLD, 13, "middle", "700")
note(cx, cy + 36, "bound to an exact digest", FAINT, 12, "middle")
curve(794, 320, 1250, 340, 0.05, GREEN)

# ── durable state and the stream out ────────────────────────────────────
region(1860, 130, 496, 560, "WHAT SURVIVES", "state outlives the process", GREEN)
for i, (ic, lb, sub) in enumerate([
        ("database", "Firestore", ["runs · events · approvals"]),
        ("server", "Cloud SQL", ["replayable history"]),
        ("artifact-registry", "GCS", ["content-addressed evidence"])]):
    node(2110, 250 + i * 150, ic, lb, sub, GREEN, 28)
curve(1618, 420, 2056, 300, 0.06, GO)
note(2110, 664, "on disagreement Cloud SQL wins", RED, 12, "middle")
note(2110, 682, "and execution fails closed", RED, 12, "middle")

node(1200, 830, "activity", "SSE fan-out", ["text/event-stream · resumable by frame id"], GO, 30)
curve(1430, 616, 1240, 796, 0.10, GO)
curve(2110, 462, 1256, 806, 0.06, GREEN)
note(1200, 930, "no timer · no random value · no generated line", GREEN, 12.5, "middle", "700")
note(1200, 958, "every visible frame originates in a persisted event", FAINT, 12, "middle")
note(50, 1010, "INGRESS → ADMISSION → STATE → EVIDENCE → STREAM   ·   authority never leaves this process", FAINT, 12.5)

svg = f'''<svg font-family="var(--font-mono-tactical)" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Keraun Go control plane">
<defs>{ICONS}</defs>
<style>
  .dg-flow {{ animation: dg-travel 1.4s linear infinite; }}
  @keyframes dg-travel {{ to {{ stroke-dashoffset: -26; }} }}
  @media (prefers-reduced-motion: reduce) {{ .dg-flow {{ animation: none; opacity: .75; }} }}
</style>
<rect width="{W}" height="{H}" fill="var(--dg-bg)"/>
{chr(10).join(p)}
</svg>'''
Path("src/web/assets/architecture/go-control-plane.svg").write_text(svg)
print("go plane:", len(svg), "bytes")
