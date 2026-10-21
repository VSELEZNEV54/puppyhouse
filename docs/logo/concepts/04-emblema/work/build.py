"""04-emblema · «Эмблема» — single source of truth for every deliverable.

python3 build.py  -> writes all SVGs into the concept folder (and colour variants into work/).
Geometry helpers live in geo.py (skia-pathops booleans, variable-width sweeps, text on arcs).
"""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import *

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)

# ---------------- palette ----------------
INK = '#141414'
CREAM = '#F3EEE4'
CORAL = '#FF967C'
NAVY = '#10375C'

# ---------------- type ----------------
SERIF = 'Literata[opsz,wght].ttf'
WM_VAR = {'wght': 600, 'opsz': 36}      # wordmark: sturdy book serif, calm weight
WM_TRACK = -0.018                       # em
ARC_VAR = {'wght': 640, 'opsz': 24}     # text on the seal: low-contrast cut survives small sizes
TAG_VAR = {'wght': 560, 'opsz': 18}     # tagline «питомник щенков»


# ---------------- the symbol: a puppy whose ears are the roof ----------------
def dog_nose(cx, ny, w, h):
    """dog nose: broad soft top, narrowing to a rounded point"""
    return rounded_poly([(cx - w / 2, ny), (cx + w / 2, ny), (cx + w * 0.12, ny + h), (cx - w * 0.12, ny + h)],
                        [w * 0.3, w * 0.3, h * 0.42, h * 0.42])


# One ribbon, one smooth curve: the slope is straight, then the curvature eases in (no kink at the
# eave), the ear swings out and comes back to the cheek. Curvature knots: (arc length, 1/units).
APEX = (100, 34)
SPINE = [(64, 0), (78, -0.016), (114, -0.008), (150, -0.022)]
SPINE_L = 150
RR, RE = 15.3, 19.0      # half-width of the roof slope (+18 % vs round 2) and of the ear (-12 %)
W0, W1 = 70, 140         # the ear widens smoothly over this stretch of arc length, then holds


def hood(rr=RR, re=RE):
    """the ribbon: left ear -> ridge -> right ear. Round outside at the ridge, crisp inside."""
    pts, _ = curv_knots(APEX, 135, SPINE, SPINE_L)
    half = sweep(polyfunc(pts), lambda u: rr + (re - rr) * smoothstep(W0, W1, u * SPINE_L), n=600, step=2.0)
    return union(half, mirror_x(half, 100))


def head():
    """200x200 grid, axis x=100: the ribbon, two eyes, a dog nose."""
    eyes = union(circle(80, 121, 10.5), circle(120, 121, 10.5))
    nose = dog_nose(100, 138, 38, 21)
    return union(hood(), eyes, nose)


HEAD = head()


def fit(p, cx, cy, h):
    """scale a path so its bbox height is h and centre it on (cx, cy)."""
    x0, y0, x1, y1 = p.bounds
    s = h / (y1 - y0)
    q = scale(p, s)
    x0, y0, x1, y1 = q.bounds
    return move(q, cx - (x0 + x1) / 2, cy - (y0 + y1) / 2)


def medallion_head(cx, cy, D):
    """the head placed in a disc of diameter D (optically centred: the pointed ridge is light,
    the ears and face carry the mass, so the bbox sits a hair low)"""
    return fit(HEAD, cx, cy + D * 0.012, D * 0.6)


# ---------------- favicon head (16-24 px) ----------------
PX16 = 12.5   # one pixel of a 16 px favicon, in the 200-unit grid


def mark16_head():
    """simplified head for 16-24 px: heavier ribbon, eyes and nose placed on the 16 px pixel grid
    (eye centres on pixel centres -> one solid dark pixel each, nose = a 2x2 px block)."""
    h = fit(hood(18, 20), 100, 100 + 200 * 0.012, 124)
    ey = 9.5 * PX16
    eyes = union(circle(6.5 * PX16, ey, 11), circle(9.5 * PX16, ey, 11))
    nose = dog_nose(100, 11 * PX16, 36, 25)
    return union(h, eyes, nose)


# ---------------- wordmark ----------------
# Two hand-made letters (Literata wght 600 opsz 36 outlines, glyph-local units at size 1000, y down):
#   д: the descender feet end in round lobes, like the ear tips of the mark;
#   ф: the wedge flag becomes a soft lobe drooping off the stem, a small floppy ear.
def d_soft(g):
    assert abs(g.bounds[3] - 156.39) < 0.5, 'д outline changed: re-check the hand-made letter'
    top = inter(g, rect(-100, -1000, 800, 1118))                       # Literata above y=118
    return union(top, circle(40.0, 118, 29.7), circle(544.5, 118, 29.9))


def f_soft(g):
    assert abs(g.bounds[1] + 770.04) < 0.5, 'ф outline changed: re-check the hand-made letter'
    body = diff(g, rect(200, -800, 289.2, 160))                        # cut the flag and the stem top
    flag = rounded_poly([(356.6, -630), (356.6, -705), (281, -688), (285, -764), (477.7, -770), (489.1, -760.3), (489.1, -630)],
                        [0, 26, 40, 22, 6, 6, 0])
    return union(body, flag)


WM_TEXT = 'домщенков.рф'
WM_KERN = {          # extra space after glyph i, em
    1: -0.004,       # о|м : round next to straight, a touch tighter
    2: 0.010,        # м|щ : picket fence, open so the foot serifs do not touch
    3: 0.004,        # щ|е
    7: -0.004,       # о|в
    8: -0.012,       # в|.  pull the dot in
    9: -0.010,       # .|р
    10: 0.006,       # р|ф : two bowls face each other, give them air
}
WM_CUSTOM = {0: d_soft, 11: f_soft}


def wordmark(F, x=0, y=0, custom=True):
    """«домщенков.рф» in Literata with the hand-made д and ф and optical spacing, at size F."""
    res = text(SERIF, WM_TEXT, 1000, WM_VAR, tracking=WM_TRACK * 1000)
    p = pathops.Path()
    shift = 0
    for i, g in enumerate(res['glyphs']):
        q = move(from_d(g['d']), -g['x'], 0)
        if custom and i in WM_CUSTOM:
            q = WM_CUSTOM[i](q)
        p = union(p, move(q, g['x'] + shift, 0))
        shift += WM_KERN.get(i, 0) * 1000
    return move(scale(p, F / 1000), x, y), res


# ---------------- descriptor «питомник щенков» ----------------
SANS = 'Geist[wght].ttf'
DESC_TEXT = 'питомник щенков'


def descriptor(F, font='geist'):
    if font == 'geist':
        return text_path(SANS, DESC_TEXT, F, {'wght': 500}, tracking=0.02 * F)
    return text_path(SERIF, DESC_TEXT, F, TAG_VAR, tracking=0.05 * F)


def xh_of(font, var):
    return text(font, 'х', 100, var)['xheight'] / 100


XH_WM = xh_of(SERIF, WM_VAR)
XH_GEIST = xh_of(SANS, {'wght': 500})
XH_TAG = xh_of(SERIF, TAG_VAR)


# ---------------- emblem (seal) ----------------
def seal(cx=200, cy=200, R=196, band=54, size=33, track_em=0.09, style='band'):
    """Layers of the round seal.
    style 'band': a solid ring with the lettering knocked out (bold, for stickers and avatars)
    style 'line': fine double rule, lettering as positive shapes (stamps, documents, premium print)."""
    r_out, r_in = R, R - band
    # text centred in the band that is actually free: outer rules eat ~9-10 units, the inner rule ~1.5
    r_mid = ((r_out - (8 if style == 'band' else 10.5)) + (r_in + (0 if style == 'band' else 1.5))) / 2 - 0.5
    tr = track_em * size
    t, at = arc_text(SERIF, 'домщенков.рф', size, ARC_VAR, cx, cy, r_mid, 'top', tracking=tr)
    b, ab = arc_text(SERIF, 'питомник щенков', size, ARC_VAR, cx, cy, r_mid, 'bottom', tracking=tr)
    gap = (360 - at - ab) / 2                    # each side gap, degrees
    side = at / 2 + gap / 2                      # centre of the gap from 12 o'clock
    dots = pathops.Path()
    for sgn in (-1, 1):
        a = math.radians(side) * sgn
        dots = union(dots, circle(cx + r_mid * math.sin(a), cy - r_mid * math.cos(a), size * 0.085))
    hd = fit(HEAD, cx, cy + (r_in * 2) * 0.012, (r_in * 2) * 0.52)
    if style == 'band':
        ringp = diff(ring(cx, cy, r_out, r_in), t, b, dots)
        ringp = diff(ringp, ring(cx, cy, r_out - 6, r_out - 8))          # fine hairline in the band
        inner = ring(cx, cy, r_in - 8, r_in - 10.5)                      # engraved rule in the field
        return dict(ink=union(ringp, inner, hd), ground=circle(cx, cy, r_out))
    rules = union(ring(cx, cy, r_out, r_out - 5), ring(cx, cy, r_out - 9, r_out - 10.5),
                  ring(cx, cy, r_in + 1.5, r_in - 1.5))
    return dict(ink=union(rules, t, b, dots, hd), ground=circle(cx, cy, r_out))


# ---------------- helpers ----------------
def tight_view(paths, pad):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for p in paths:
        x0, y0, x1, y1 = p.bounds
        xs0.append(x0); ys0.append(y0); xs1.append(x1); ys1.append(y1)
    x0, y0, x1, y1 = min(xs0), min(ys0), max(xs1), max(ys1)
    return (x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad)


def write(name, content):
    with open(os.path.join(OUT, name), 'w') as f:
        f.write(content)


def lockup_parts(D=100, xh_ratio=0.28, gap_ratio=0.2):
    cx = cy = D / 2
    disc = circle(cx, cy, D / 2)
    hd = medallion_head(cx, cy, D)
    F = D * xh_ratio / XH_WM
    x_text = D + D * gap_ratio
    wm, _ = wordmark(F)
    x0 = wm.bounds[0]
    wm = move(wm, x_text - x0, cy + F * XH_WM / 2)      # x-height band centred on the disc
    return disc, hd, wm


def lockup_tagline_parts(D=100, font='geist', wm_xh=0.25, desc_xh=0.115, gap_ratio=0.2):
    """medallion + two-line text block: the wordmark, and under it «питомник щенков».
    The two lines are centred as a block on the disc; the descriptor starts at the wordmark's stem."""
    cx = cy = D / 2
    disc = circle(cx, cy, D / 2)
    hd = medallion_head(cx, cy, D)
    F = D * wm_xh / XH_WM
    x_text = D + D * gap_ratio
    wm, _ = wordmark(F)
    wm = move(wm, x_text - wm.bounds[0], 0)
    xh_d = (XH_GEIST if font == 'geist' else XH_TAG)
    Fd = D * desc_xh / xh_d
    ds, _ = descriptor(Fd, font)
    ds = move(ds, x_text - ds.bounds[0] + F * 0.01, 0)
    # vertical: wordmark x-height band and descriptor x-height band, gap between them = 0.17 D
    gap = 0.2 * D
    top_wm = -F * XH_WM                 # wordmark baseline at 0
    base_d = gap + Fd * xh_d            # descriptor baseline
    block_top, block_bot = top_wm, base_d
    dy = cy - (block_top + block_bot) / 2
    return disc, hd, move(wm, 0, dy), move(ds, 0, dy + base_d)


# ---------------- favicon pixel sheet (shows how mark-16 lands on the 16 / 24 px grid) ----------------
def flatten(p, steps=12):
    """pathops Path -> list of closed polygons (curves sampled)."""
    polys, cur, last = [], [], None
    for verb, pts in p.segments:
        if verb == 'moveTo':
            cur = [pts[0]]; last = pts[0]
        elif verb == 'lineTo':
            cur.append(pts[0]); last = pts[0]
        elif verb == 'curveTo':
            c1, c2, e = pts
            for i in range(1, steps + 1):
                t = i / steps; u = 1 - t
                cur.append((u**3*last[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t**3*e[0],
                            u**3*last[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t**3*e[1]))
            last = e
        elif verb == 'qCurveTo':
            *offs, e = pts
            if e is None:
                offs = list(offs); e = ((offs[-1][0] + offs[0][0]) / 2, (offs[-1][1] + offs[0][1]) / 2)
                cur = [e]; last = e; offs = offs + [offs[0]]
            for j, c in enumerate(offs):
                end = e if j == len(offs) - 1 else ((c[0] + offs[j + 1][0]) / 2, (c[1] + offs[j + 1][1]) / 2)
                for i in range(1, steps + 1):
                    t = i / steps; u = 1 - t
                    cur.append((u*u*last[0] + 2*u*t*c[0] + t*t*end[0], u*u*last[1] + 2*u*t*c[1] + t*t*end[1]))
                last = end
        elif verb == 'closePath':
            if cur: polys.append(cur)
            cur = []
    if cur: polys.append(cur)
    return polys


def raster(layers, size, bg='#FFFFFF', ss=16):
    """box-filtered rasterisation of [(path in the 200 grid, colour)] at size x size px."""
    from PIL import Image, ImageDraw
    N = size * ss
    im = Image.new('RGB', (N, N), bg)
    dr = ImageDraw.Draw(im)
    k = N / 200
    for p, col in layers:
        for poly in flatten(p):
            dr.polygon([(x * k, y * k) for x, y in poly], fill=col)
    im = im.resize((size, size), Image.BOX)
    return [[im.getpixel((x, y)) for x in range(size)] for y in range(size)]


def pixel_tile(px, x0, y0, side):
    """pixels as vector squares (one path per colour), drawn side x side at (x0, y0)."""
    n = len(px); c = side / n
    by = {}
    for j, row in enumerate(px):
        for i, (r, g, b) in enumerate(row):
            by.setdefault('#%02X%02X%02X' % (r, g, b), []).append(rect(x0 + i * c - 0.2, y0 + j * c - 0.2, c + 0.4, c + 0.4))
    return [(union(*sq), col) for col, sq in by.items()]


def favicon_sheet(m16, m):
    """extra-favicon.svg: mark-16 rasterised at 16 and 24 px, mark.svg at 32 px, each zoomed to 180."""
    bg = circle(100, 100, 100)
    tiles = [(m16, 16, '16 px · mark-16.svg'), (m16, 24, '24 px · mark-16.svg'), (m, 32, '32 px · mark.svg')]
    layers, S, G = [], 180, 36
    W = len(tiles) * S + (len(tiles) - 1) * G
    for t, (head_, size, label) in enumerate(tiles):
        x = t * (S + G)
        layers += pixel_tile(raster([(bg, CORAL), (head_, INK)], size), x, 0, S)
        lab, _ = text_path(SANS, label, 15, {'wght': 500})
        lx0, _, lx1, _ = lab.bounds
        layers.append((move(lab, x + S / 2 - (lx0 + lx1) / 2, S + 30), INK))
    return svg((0, 0, W, S + 40), layers)


def build():
    # ---- lockups
    disc, hd, wm = lockup_parts()
    view = tight_view([disc, wm], 3)
    write('lockup.svg', svg(view, [(disc, CORAL), (hd, INK), (wm, INK)]))
    write('lockup-inverse.svg', svg(view, [(diff(disc, hd), CORAL), (wm, CREAM)]))
    # mono: a stamp-like ring + the positive puppy, the same figure as the colour version
    rg = ring(50, 50, 50, 45.6)
    mono = svg(view, [(union(rg, hd), INK), (wm, INK)])
    write('lockup-mono.svg', mono)
    # on coral grounds the coral disc would vanish: use the one-colour medallion (same drawing as mono)
    write('lockup-on-coral.svg', mono)

    # ---- lockup with the descriptor «питомник щенков» (Avito, documents, signage)
    disc_t, hd_t, wm_t, ds_t = lockup_tagline_parts(font='geist')
    view_t = tight_view([disc_t, wm_t, ds_t], 3)
    write('lockup-tagline.svg', svg(view_t, [(disc_t, CORAL), (hd_t, INK), (wm_t, INK), (ds_t, INK)]))
    write('work/lockup-tagline-inverse.svg', svg(view_t, [(diff(disc_t, hd_t), CORAL), (union(wm_t, ds_t), CREAM)]))
    write('work/lockup-tagline-mono.svg', svg(view_t, [(union(ring(50, 50, 50, 45.6), hd_t, wm_t, ds_t), INK)]))
    d2, h2, w2, s2 = lockup_tagline_parts(font='serif')
    write('work/lockup-tagline-serif.svg', svg(tight_view([d2, w2, s2], 3), [(d2, CORAL), (h2, INK), (w2, INK), (s2, INK)]))

    # ---- mark (avatar, favicon 32 px and up): coral disc, ink puppy
    bgp = circle(100, 100, 100)
    hm = medallion_head(100, 100, 200)
    write('mark.svg', svg((0, 0, 200, 200), [(bgp, CORAL), (hm, INK)]))
    write('mark-mono.svg', svg((0, 0, 200, 200), [(union(ring(100, 100, 100, 90), hm), INK)]))
    write('work/mark-mono-solid.svg', svg((0, 0, 200, 200), [(diff(bgp, hm), INK)]))
    # ---- favicon 16-24 px: simplified head on the pixel grid
    m16 = mark16_head()
    write('mark-16.svg', svg((0, 0, 200, 200), [(bgp, CORAL), (m16, INK)]))
    write('extra-favicon.svg', favicon_sheet(m16, hm))

    # ---- seal
    sb = seal(style='band')
    sl = seal(style='line')
    V = (0, 0, 400, 400)
    write('extra-badge.svg', svg(V, [(sb['ground'], CORAL), (sb['ink'], INK)]))
    write('work/badge-line-coral.svg', svg(V, [(sl['ground'], CORAL), (sl['ink'], INK)]))
    write('work/badge-line-cream.svg', svg(V, [(sl['ground'], CREAM), (sl['ink'], INK)]))
    write('work/badge-band-navy.svg', svg(V, [(sb['ground'], CREAM), (sb['ink'], NAVY)]))
    write('work/badge-mono.svg', svg(V, [(sl['ink'], INK)]))

    # ---- stacked: square coral tile, ink puppy + wordmark + descriptor (2 colours)
    T = 400
    tile = rrect(0, 0, T, T, 56)
    h3 = fit(HEAD, T / 2, 0, 124)
    F = 38
    wm3, _ = wordmark(F)
    Fd = F * 0.6 * XH_WM / XH_GEIST                  # descriptor x-height = 0.6 of the name's
    tg, _ = descriptor(Fd, 'geist')
    hy0, hy1 = h3.bounds[1], h3.bounds[3]
    base = hy1 + 30 + F * XH_WM
    x0, _, x1, _ = wm3.bounds
    wm3 = move(wm3, T / 2 - (x0 + x1) / 2, base)
    tx0, _, tx1, _ = tg.bounds
    tg = move(tg, T / 2 - (tx0 + tx1) / 2, base + F * 0.3 + Fd * XH_GEIST + 16)
    gy0, gy1 = h3.bounds[1], tg.bounds[3]
    dy = T / 2 - (gy0 + gy1) / 2
    h3, wm3, tg = [move(q, 0, dy) for q in (h3, wm3, tg)]
    write('stacked.svg', svg((0, 0, T, T), [(tile, CORAL), (union(h3, wm3, tg), INK)]))

    # ---- application: puppy passport cover, navy + cream, the fine-line seal
    W, H = 300, 420
    cover = rrect(0, 0, W, H, 18)
    s_ = 0.64
    ecx, ecy = W / 2, 172
    em = move(scale(sl['ink'], s_), ecx - 200 * s_, ecy - 200 * s_)
    title, _ = text_path(SERIF, 'паспорт щенка', 23, {'wght': 560, 'opsz': 24}, tracking=0.04 * 23)
    x0, y0, x1, y1 = title.bounds
    title = move(title, W / 2 - (x0 + x1) / 2, 352)
    rule = rrect(W / 2 - 14, 370, 28, 1.6, 0.8)
    write('extra-passport.svg', svg((0, 0, W, H), [(cover, NAVY), (union(em, title, rule), CREAM)]))

    # ---- application: a sign on a coral plate = the coral rule + the descriptor lockup
    SW, SH = 640, 220
    plate = rrect(0, 0, SW, SH, 26)
    k = 1.08
    parts = [scale(p, k) for p in (hd_t, wm_t, ds_t)]
    rg_t = scale(ring(50, 50, 50, 45.6), k)
    grp = union(rg_t, *parts)
    bx = tight_view([scale(disc_t, k), parts[1], parts[2]], 0)
    grp = move(grp, SW / 2 - (bx[0] + bx[2] / 2), SH / 2 - (bx[1] + bx[3] / 2))
    write('extra-sign.svg', svg((0, 0, SW, SH), [(plate, CORAL), (grp, INK)]))


if __name__ == '__main__':
    build()
    print('built')
