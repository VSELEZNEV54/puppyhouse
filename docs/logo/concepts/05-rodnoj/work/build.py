"""05-rodnoj · «Родной сайту» — single source of truth for every deliverable (v3, final polish).

Mark: the site's coral tile (r = 30 %, as .logo__mark 12/40) with a puppy asleep at home. Two floppy ink ears,
each the hull of three circles (root, shoulder, lobe), hang INSIDE the tile: everything that matters sits in the
central 80 % circle, so a round avatar crops nothing and the same mark works on dark backgrounds without a rim.
Closed eyes are soft lids (a lune between two arcs, rounded tips), the nose is a dog nose (hull of three circles).
mark-awake.svg has identical geometry with open eyes, so CSS can swap the two on hover.
mark-16.svg is a separate pixel-fitted favicon on a 16 grid.
Wordmark: Geist (the site's font) as outlines, hand-kerned; the «щ» descender is Geist's own «j» hook, mirrored.
«.рф» is the same ink as the word.

  python3 build.py            -> writes all SVGs into the concept folder
"""
import os, math
from lib import *
from geo import hull, lune

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

INK = '#141414'
CORAL = '#FF967C'
MUTED = '#6B6B6B'       # tagline on light
PAGE = '#F3F2EF'
CREAM = '#F3F2EF'       # name on dark
MUTED_INV = '#A3A19C'   # tagline on dark
SAND = '#EBDCC7'
WHITE = '#FFFFFF'

WGHT = 530        # name
TAG_WGHT = 450    # tagline

# ───────────────────────── mark (100 × 100 grid) ─────────────────────────
TILE_R = 30
SAFE_R = 40       # central 80 %: every ear / face point stays inside this circle around (50; 50)


def tile(inset=0):
    return rrect(inset, inset, 100 - 2 * inset, 100 - 2 * inset, TILE_R - inset)


def mirror(p, w=100):
    return T(p, -1, 0, 0, 1, w, 0)


# floppy ear = hull of three circles: root (where it folds over the skull), shoulder, heavy round lobe
EAR = [((33.5, 31.5), 3.5), ((26.5, 32), 4.5), ((21.5, 60.5), 9.6)]


def ears():
    l = hull(EAR)
    return U(l, mirror(l))


# closed eyes: soft lids (lower lune of two arcs through the same tips, tips rounded)
EYE = dict(y=58.5, gap=17.5, chord=12.4, t=4.4, sag=4.3, soft=1.0)
AWAKE_R = 3.4


def eyes(state='asleep'):
    e = EYE
    if state == 'awake':
        # open eyes: two calm dots where the lids were (centred on the lid's visual middle)
        return U(*[circle(50 + s * e['gap'] / 2, e['y'] - 2.9, AWAKE_R) for s in (-1, 1)])
    return U(*[lune(50 + s * e['gap'] / 2, e['y'], e['chord'], e['t'], e['sag'], e['soft']) for s in (-1, 1)])


NOSE = dict(top=63.5, w=15, h=10.5, ru=3.8, rb=2.3)


def nose(n=NOSE):
    ru, rb = n['ru'], n['rb']
    return hull([((50 - n['w'] / 2 + ru, n['top'] + ru), ru), ((50 + n['w'] / 2 - ru, n['top'] + ru), ru),
                 ((50, n['top'] + n['h'] - rb), rb)])


def face(state='asleep'):
    return U(eyes(state), nose())


def mark_body(variant='color', state='asleep', tile_fill=CORAL):
    """returns list of (path, fill) in the 100 grid"""
    if variant in ('color', 'inverse'):
        # the ears never touch the tile edge, so the same drawing works on light and dark grounds
        return [(tile(), tile_fill), (ears(), INK), (face(state), INK)]
    if variant == 'mono':
        # single colour: the tile is drawn as an outline, like the site's line icons; ears + face solid
        sw = 6.0
        ring = SUB(tile(), tile(sw))
        return [(U(ring, ears(), face(state)), INK)]
    raise ValueError(variant)


# ───────────────────────── favicon (16 × 16 grid, pixel-fitted) ─────────────────────────
# At 16 px there is no room for the 80 % margin: the ears move out towards the tile edge, the eyes become one
# thick dash each (closed eyes), placed level with the narrow upper part of the ears, and the nose grows and sits
# between the lobes. Edges are put on whole / half pixels.
F16 = dict(r=4.5,
           ear=[((2.75, 4.0), 1.0), ((2.6, 9.9), 1.7)],
           eye=(5.0, 6.0, 2.0, 1.5, 0.6),          # left eye: x, y, w, h, corner radius (right one mirrored)
           nose=dict(top=9.0, w=4.0, h=2.6, ru=1.0, rb=0.7))


def mark16_body(variant='color'):
    f = F16
    t = rrect(0, 0, 16, 16, f['r'])
    l = hull(f['ear'])
    e = U(l, mirror(l, 16))
    x, y, w, h, r = f['eye']
    le = rrect(x, y, w, h, r)
    ey = U(le, mirror(le, 16))
    n = f['nose']
    no = hull([((8 - n['w'] / 2 + n['ru'], n['top'] + n['ru']), n['ru']), ((8 + n['w'] / 2 - n['ru'], n['top'] + n['ru']), n['ru']),
               ((8, n['top'] + n['h'] - n['rb']), n['rb'])])
    return [(t, CORAL), (e, INK), (U(ey, no), INK)]


# ───────────────────────── wordmark ─────────────────────────
WORD = 'домщенков.рф'
# extra space before glyph i, in em/1000 (on top of Geist's own spacing + tracking)
KERN = {
    1: -12,   # д|о   the д foot leaves a hole at the baseline
    2: -2,    # о|м
    3: 6,     # м|щ   picket fence: five stems in a row — open the joint, it also hints «дом | щенков»
    4: -2,    # щ|е   the new tail runs under the е, nothing collides above the baseline
    5: 2,     # е|н
    6: 4,     # н|к
    7: -16,   # к|о   the diagonal leaves a hole
    8: -4,    # о|в
    9: -26,   # в|.
    10: -24,  # .|р
    11: -4,   # р|ф
}
TRACK = -10  # em/1000


def shch_tail(g, size, base):
    """«щ»: swap the stock rectangular descender for Geist's own «j» hook, mirrored (turns right, flat cut).
    Depth = the font's descender (р, ф, j all end at 150/1000)."""
    s = size / 1000
    p = g['path']
    below = AND(p, P(f"M{g['x'] - 50} {base + 2 * s}H{g['x'] + 2000 * s}V{base + 400 * s}H{g['x'] - 50}Z"))
    dx0, _, dx1, _ = below.bounds          # stock descender (x extents)
    stem = dx1 - dx0
    body = SUB(p, P(f"M{dx0 - 1} {base + 0.5 * s}H{dx1 + 1}V{base + 400 * s}H{dx0 - 1}Z"))
    # Geist «j» (wght 530, 1000 upm): stem x 104.58..217.18, hook to y 150, terminal 90.4 thick, cut at x −3.96
    k = stem / (112.6 * s)      # weight-adaptive: hook stem = this weight's descender width
    jx = lambda X: dx0 + (217.18 - X) * s * k
    jy = lambda Y: base + Y * s
    reach = -3.96 + 6          # terminal a hair shorter than j: it must not reach under the е's bowl too far
    d = (f"M{jx(reach)} {jy(150)}L{jx(reach)} {jy(59.62)}L{jx(46.06)} {jy(59.62)}"
         f"Q{jx(73.62)} {jy(59.62)} {jx(89.10)} {jy(47.25)}Q{jx(104.58)} {jy(34.88)} {jx(104.58)} {jy(0.84)}"
         f"L{jx(104.58)} {jy(-30)}L{jx(217.18)} {jy(-30)}L{jx(217.18)} {jy(4.84)}"
         f"Q{jx(217.18)} {jy(83.16)} {jx(182.15)} {jy(116.58)}Q{jx(147.12)} {jy(150)} {jx(63.68)} {jy(150)}Z")
    return U(body, P(d))


def wordmark(size, x=0, y=0, wght=None, ink=INK, tail=True):
    wght = wght or WGHT
    kern = {i: v * size / 1000 for i, v in KERN.items()}
    gl, info = text(WORD, size, wght, TRACK * size / 1000, x, y, kern=kern)
    out = []
    for i, g in enumerate(gl):
        p = g['path']
        if g['char'] == 'щ' and tail:
            p = shch_tail(g, size, y)
        out.append((p, ink))   # «.рф» in the same ink as the word: the domain is the name
    return out


def tagline(size, x=0, y=0, fill=MUTED, wght=None, txt='питомник щенков', track=0.02):
    gl, info = text(txt, size, wght or TAG_WGHT, track * size, x, y)
    return [(g['path'], fill) for g in gl if g['path'].bounds and g['path'].bounds[0] != g['path'].bounds[2]]


def ink_bounds(items):
    xs0, ys0, xs1, ys1 = [], [], [], []
    for p, _ in items:
        b = p.bounds
        if b is None or (b[0] == b[2]):
            continue
        xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
    return min(xs0), min(ys0), max(xs1), max(ys1)


def place(items, dx=0, dy=0, s=1):
    return [(T(p, s, 0, 0, s, dx, dy), f) for p, f in items]


def render(items, pad=None, bg=None, vb=None):
    x0, y0, x1, y1 = vb or ink_bounds(items)
    if pad is not None:
        x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    w, h = x1 - x0, y1 - y0
    body = ''
    groups = []
    for p, f in items:
        if groups and groups[-1][1] == f:
            groups[-1][0].append(p)
        else:
            groups.append(([p], f))
    for ps, f in groups:
        d = ''.join(D(p) for p in ps)
        body += f'<path fill="{f}" d="{d}"/>'
    bgr = f'<rect x="{fmt(x0)}" y="{fmt(y0)}" width="{fmt(w)}" height="{fmt(h)}" fill="{bg}"/>' if bg else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(x0)} {fmt(y0)} {fmt(w)} {fmt(h)}">'
            f'{bgr}{body}</svg>\n')


# ───────────────────────── lockups ─────────────────────────
WM_SIZE = 56         # v2: 48 — the tile is now ~15 % smaller relative to the text block
TAG_SIZE = 32        # v2: 28 — 12.8 px in a 40 px header, 10.9 px in the 34 px phone header
GAP = 25             # = the site's .logo gap (10 px at a 40 px tile)
BASE_NAME = 45.5     # name baseline in the 100 tile
BASE_TAG = 86.5      # tagline baseline


def lockup(variant='color'):
    if variant == 'color':
        mk, ink, tg = mark_body('color'), INK, MUTED
    elif variant == 'inverse':
        mk, ink, tg = mark_body('inverse'), CREAM, MUTED_INV
    else:
        mk, ink, tg = mark_body('mono'), INK, INK
    tw = 400 if variant == 'mono' else None   # one colour: the tagline steps back by weight instead of grey
    x = 100 + GAP
    wm = wordmark(WM_SIZE, x, BASE_NAME, ink=ink)
    dx_ink = wm[0][0].bounds[0]
    tl = tagline(TAG_SIZE, 0, BASE_TAG, fill=tg, wght=tw)
    tx = tl[0][0].bounds[0]
    tl = place(tl, dx_ink - tx + 0.4)     # tagline starts on the ink of «д» (optically: п's flat stem)
    return mk + wm + tl


def stacked_items(variant='color'):
    S = 2.2
    ink, tg = (INK, MUTED) if variant == 'color' else (CREAM, MUTED_INV)
    mk = place(mark_body('color'), 0, 0, S)
    cx = 50 * S
    wm = wordmark(WM_SIZE, 0, 0, ink=ink)
    b = ink_bounds(wm)
    wm_base = 100 * S + 30 + 0.53 * WM_SIZE
    wm = place(wm, cx - (b[0] + b[2]) / 2, wm_base)
    tl = tagline(TAG_SIZE * 0.9, 0, 0, fill=tg)
    bt = ink_bounds(tl)
    tl = place(tl, cx - (bt[0] + bt[2]) / 2, wm_base + 44)
    return mk + wm + tl


def stacked():
    """square sticker / social format: the site's white tile, mark on top, name, tagline"""
    items = stacked_items('color')
    x0, y0, x1, y1 = ink_bounds(items)
    side = max(x1 - x0, y1 - y0) + 2 * 44
    ccx, ccy = (x0 + x1) / 2, (y0 + y1) / 2
    card = (rrect(ccx - side / 2, ccy - side / 2, side, side, side * 0.16), WHITE)
    return [card] + items


def stacked_inverse():
    """the same stack for dark grounds, no plate: coral tile as is, cream name, light-grey tagline"""
    return stacked_items('inverse')


# ───────────────────────── extras ─────────────────────────
def label(txt, size, cx, y, fill=MUTED, wght=460):
    lb = tagline(size, 0, 0, fill=fill, wght=wght, txt=txt, track=0.01)
    b = ink_bounds(lb)
    return place(lb, cx - (b[0] + b[2]) / 2, y)


def extra_wake():
    """the site behaviour: the puppy sleeps in the header; on hover (and on «заявка отправлена») it wakes up.
    mark.svg and mark-awake.svg share every coordinate except the eyes."""
    items = []
    col = 150
    states = [('asleep', 'в шапке: спит'), ('awake', 'при наведении: проснулся')]
    for i, (st, cap) in enumerate(states):
        x = i * col
        items += place(mark_body('color', st), x, 0)
        items += label(cap, 12, x + 50, 126)
    x0, y0, x1, y1 = ink_bounds(items)
    pad = 30
    card = (rrect(x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, 28), WHITE)
    return [card] + items


def extra_grounds():
    """where the colour lockup cannot go as is: dark grounds (inverse, no plate) and the coral ground (single colour)"""
    items = []
    H1 = 300
    lk = lockup('inverse')
    b = ink_bounds(lk)
    s = 0.9
    lw = (b[2] - b[0]) * s
    st = stacked_inverse()
    b2 = ink_bounds(st)
    s2 = 210 / (b2[3] - b2[1])
    sw_ = (b2[2] - b2[0]) * s2
    W1 = 48 + lw + 80 + sw_ + 48
    items.append((rrect(0, 0, W1, H1, 28), INK))
    items += place(lk, 48 - b[0] * s, (H1 - (b[3] - b[1]) * s) / 2 - b[1] * s, s)
    items += place(st, 48 + lw + 80 - b2[0] * s2, (H1 - 210) / 2 - b2[1] * s2, s2)
    X2 = W1 + 24
    lm = lockup('mono')
    b3 = ink_bounds(lm)
    s3 = s
    W2 = (b3[2] - b3[0]) * s3 + 96
    items.append((rrect(X2, 0, W2, H1, 28), CORAL))
    items += place(lm, X2 + 48 - b3[0] * s3, (H1 - (b3[3] - b3[1]) * s3) / 2 - b3[1] * s3, s3)
    return items


def pixels(svg_text, px, bg=WHITE):
    """rasterize an SVG at px × px exactly as a browser does (Chromium, via raster.mjs) -> list of rows of hex colours"""
    import subprocess, tempfile
    from PIL import Image
    here = os.path.dirname(os.path.abspath(__file__))
    with tempfile.TemporaryDirectory() as td:
        sp, pp = os.path.join(td, 'm.svg'), os.path.join(td, 'm.png')
        open(sp, 'w').write(svg_text)
        subprocess.run(['node', os.path.join(here, 'raster.mjs'), sp, pp, str(px), bg], check=True)
        im = Image.open(pp).convert('RGB')
        return [['#%02X%02X%02X' % im.getpixel((x, y)) for x in range(px)] for y in range(px)]


def pixel_items(rows, x0, y0, cell):
    out = []
    for j, row in enumerate(rows):
        i = 0
        while i < len(row):
            k = i
            while k + 1 < len(row) and row[k + 1] == row[i]:
                k += 1
            # runs overlap the next ones by a hair, so the enlarged pixels show no anti-aliasing seams
            out.append((rrect(x0 + i * cell, y0 + j * cell, (k - i + 1) * cell + 0.6, cell + 0.6, 0), row[i]))
            i = k + 1
    return out


def extra_favicon():
    """the browser tab, honestly: both marks rasterized at real size by Chromium, then every pixel enlarged"""
    big = render(mark_body('color'), vb=(0, 0, 100, 100))
    small = render(mark16_body(), vb=(0, 0, 16, 16))
    cols = [(pixels(big, 16), 12, 'mark.svg в 16 px'), (pixels(small, 16), 12, 'mark-16.svg в 16 px'),
            (pixels(big, 32), 6, 'mark.svg в 32 px')]
    items, x = [], 0
    for rows, cell, cap in cols:
        items += pixel_items(rows, x, 0, cell)
        items += label(cap, 13, x + 96, 222)
        x += 192 + 56
    x0, y0, x1, y1 = ink_bounds(items)
    pad = 30
    card = (rrect(x0 - pad, y0 - pad, x1 - x0 + 2 * pad, y1 - y0 + 2 * pad, 28), WHITE)
    return [card] + items


def extra_passport():
    """puppy's passport / contract folder: sand cover, single-colour mark, the name, three fields"""
    W, H = 300, 420
    items = [(rrect(0, 0, W, H, 22), SAND)]
    items.append((rrect(22, 0, 3, H, 0), '#DCC9AE'))
    cx = W / 2 + 12
    items += place(mark_body('mono'), cx - 50, 78, 1.0)
    wm = wordmark(30, 0, 0, ink=INK)
    b = ink_bounds(wm)
    items += place(wm, cx - (b[0] + b[2]) / 2, 236)
    items += label('паспорт щенка', 15, cx, 264, fill=MUTED, wght=460)
    fields = [tagline(10.5, 0, 0, fill=MUTED, wght=460, txt=f, track=0.02) for f in ('кличка', 'порода', 'дата рождения')]
    x_line = 52 + max(ink_bounds(lb)[2] - ink_bounds(lb)[0] for lb in fields) + 12
    for i, lb in enumerate(fields):
        y = 322 + i * 26
        items += place(lb, 52 - ink_bounds(lb)[0], y)
        items.append((rrect(x_line, y + 0.5, W - x_line - 32, 1.1, 0), '#BFAE95'))
    return items


def max_radius(p, c=(50, 50)):
    """largest distance of a path from the tile centre (curves sampled) — the round-avatar safety check"""
    from fontTools.pens.recordingPen import RecordingPen
    rp = RecordingPen()
    p.draw(rp)
    m, cur = 0, None
    for op, pts in rp.value:
        if op in ('moveTo', 'lineTo'):
            cur = pts[0]
            m = max(m, math.dist(cur, c))
        elif op in ('curveTo', 'qCurveTo'):
            ps = [cur] + list(pts)
            for k in range(1, 25):
                t, q = k / 24, ps[:]
                while len(q) > 1:
                    q = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(q, q[1:])]
                m = max(m, math.dist(q[0], c))
            cur = pts[-1]
    return m


def write(name, s):
    with open(os.path.join(OUT, name), 'w') as fh:
        fh.write(s)


def main():
    PAD = 2
    for st in ('asleep', 'awake'):
        r = max_radius(U(ears(), face(st)))
        assert r <= SAFE_R, f'{st}: ears/face reach r {r:.2f} > {SAFE_R}'
        print(f'{st}: everything inside r {r:.2f} of 50 (central {2 * r:.0f} %)')
    write('lockup.svg', render(lockup('color'), pad=PAD))
    write('lockup-inverse.svg', render(lockup('inverse'), pad=PAD))
    write('lockup-mono.svg', render(lockup('mono'), pad=PAD))
    write('mark.svg', render(mark_body('color'), vb=(0, 0, 100, 100)))
    write('mark-awake.svg', render(mark_body('color', 'awake'), vb=(0, 0, 100, 100)))
    write('mark-mono.svg', render(mark_body('mono'), vb=(0, 0, 100, 100)))
    write('mark-16.svg', render(mark16_body(), vb=(0, 0, 16, 16)))
    write('stacked.svg', render(stacked(), pad=0))
    write('stacked-inverse.svg', render(stacked_inverse(), pad=PAD))
    write('extra-wake.svg', render(extra_wake(), pad=0))
    write('extra-grounds.svg', render(extra_grounds(), pad=0))
    write('extra-favicon.svg', render(extra_favicon(), pad=0))
    write('extra-passport.svg', render(extra_passport(), vb=(0, 0, 300, 420)))
    print('ok', OUT)


if __name__ == '__main__':
    main()
