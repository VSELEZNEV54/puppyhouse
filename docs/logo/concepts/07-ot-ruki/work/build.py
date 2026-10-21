#!/usr/bin/env python3
"""07-ot-ruki «От руки» v2 — single source of truth for every deliverable.

Wordmark: Caveat 700 (contextual ss01/ss02 alternates fixed per letter), laid out by hand with optical
kerning, lightly smoothed and only slightly thickened (felt-tip pen, not a marker), the ascender of «д»
lowered so a hand-drawn roof can sit over «дом». The roof is a custom brush stroke in the same weight as
the letters. Tagline: Geist 400. All coordinates in font units of a 200-unit em, y down.
Run: python3 build.py   (writes all SVGs into the concept folder)
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import *

OUT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
CV = 'Caveat[wght].ttf'; GE = 'Geist[wght].ttf'
INK = '#141414'; ROOF = '#EC5532'; PEACH = '#FF967C'; CREAM = '#F3F2EF'
NAVY = '#10375C'; MUTED = '#6B6B6B'; MUTED_INV = '#A9A49B'; NAVY_MUTED = '#8FA6BD'
SZ = 200; WGHT = 700

# ---------------------------------------------------------------- parameters (tuned on renders)
TH = 1.6                  # round offset added to Caveat strokes (total)
STEM = 15.5 + TH          # resulting stem weight = roof weight (same pen)
S1, S2 = 1.0, 3.2
DSHIFT = 21               # ascender of «д» lowered by this much
DESC = {'uni0440': 9, 'uni0444.ss01': 6}   # descenders of «р», «ф» shortened (keeps the header lockup taller)
TRACK = 1.0
# glyph names = Caveat's own contextual choice for this word (calt), frozen so the logo never changes
NAMES = {'д': 'uni0434', 'о': 'uni043E', 'м': 'uni043C.ss01', 'щ': 'uni0449.ss02', 'е': 'uni0435.ss01',
         'н': 'uni043D', 'к': 'uni043A.ss01', 'о2': 'uni043E.ss02', 'в': 'uni0432.ss02', '.': 'period',
         'р': 'uni0440', 'ф': 'uni0444.ss01', 'а': 'uni0430', 'с': 'uni0441', 'т': 'uni0442', 'и': 'uni0438',
         'л': 'uni043B', 'ь': 'uni044C', 'п': 'uni043F', 'у': 'uni0443', 'ч': 'uni0447', 'ш': 'uni0448'}
WORD = ['д', 'о', 'м', 'щ', 'е', 'н', 'к', 'о2', 'в', '.', 'р', 'ф']
# optical kerning: extra space BEFORE glyph i (font units)
KERN = {1: -1, 2: 0, 3: 2, 4: 1, 5: 1, 6: 0, 7: -2, 8: 0, 9: 4, 10: -2, 11: -1}

ROOF_PITCH = 27.0         # degrees
ROOF_OVER = 10.0          # overhang beyond «д» and «м»
ROOF_W = 1.18             # roof weight / stem (Caveat's diagonals read heavier than its stems)
ROOF_GAP = 14.0           # clear space between roof underside and the hook of «д»


def U(ps):
    acc = ps[0]
    for p in ps[1:]:
        acc = P_union(acc, p)
    return acc

# ---------------------------------------------------------------- smoothing with adaptive knots (light files)
def smooth_adaptive(d, sigma, base=6.0, minstep=1.6, step=0.4):
    """gaussian-smooth each contour, then refit with chord-length Catmull-Rom through adaptive knots:
    dense where the outline turns, sparse on straight runs."""
    fp = FlatPen(step); parse_path(d, fp)
    out = []
    for c in fp.contours:
        if len(c) < 3: continue
        arr, L = resample(c, step)
        sm = gsmooth(arr, sigma / step) if sigma else arr
        n = len(sm)
        tg = np.roll(sm, -1, 0) - np.roll(sm, 1, 0)
        ang = np.arctan2(tg[:, 1], tg[:, 0])
        turn = np.abs(np.angle(np.exp(1j * (np.roll(ang, -1) - ang))))      # radians per sample
        kn = [0]; acc = 0.0
        for i in range(1, n):
            ds = math.hypot(*(sm[i] - sm[i - 1]))
            acc += ds + turn[i] * 7.0
            if acc >= base and ds > 0 and math.hypot(*(sm[i] - sm[kn[-1]])) >= minstep:
                kn.append(i); acc = 0.0
        if n - kn[-1] < 3 and len(kn) > 3: kn.pop()
        pts = sm[kn]
        if len(pts) < 4: continue
        out.append(cr_chord(pts))
    return ''.join(out)

def cr_chord(P):
    """closed chord-length Catmull-Rom -> cubic beziers (no overshoot with uneven knots)."""
    n = len(P); f = r2
    d = f'M{f(P[0][0])} {f(P[0][1])}'
    def T(i):
        a, b, c = P[(i - 1) % n], P[i % n], P[(i + 1) % n]
        d0 = math.hypot(*(b - a)) or 1e-6; d1 = math.hypot(*(c - b)) or 1e-6
        # Bessel tangent
        return ((b - a) / d0 * d1 + (c - b) / d1 * d0) / (d0 + d1)
    for i in range(n):
        p1 = P[i]; p2 = P[(i + 1) % n]; L = math.hypot(*(p2 - p1))
        c1 = p1 + T(i) * L / 3; c2 = p2 - T(i + 1) * L / 3
        d += f'C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p2[0])} {f(p2[1])}'
    return d + 'Z'

# ---------------------------------------------------------------- lettering
def script(keys, tracking=TRACK, kern=None, short_d=True, th=TH, s2=S2, dxs=1.0, wght=WGHT):
    """hand-set line of Caveat glyphs. returns (Path, glyph list with bboxes in final coordinates)."""
    kern = kern or {}
    x = 0.0; parts = []; gl = []
    for i, k in enumerate(keys):
        name = NAMES.get(k, k)
        g = G(CV, name, SZ, {'wght': wght}, 0, 0)
        x += kern.get(i, 0.0)
        if g['d']:
            warp = None
            if name in DESC:
                sh = DESC[name]
                def warp(a, sh=sh):
                    a = a.copy(); k = smoothstep(4, 40, a[:, 1]); a[:, 1] -= sh * k; return a
            if name.startswith('uni0434'):
                bb = g['bbox']; cx = (bb[0] + bb[2]) / 2
                lw = lower_top(-84, -130, DSHIFT if short_d else 0)
                def warp(a, lw=lw, cx=cx):
                    a = lw(a); a[:, 0] = cx + (a[:, 0] - cx) * dxs; return a
            d = smooth_d(g['d'], S1, 3.0, warp=warp)
            d = move(d, x, 0)
            parts.append(P_from_d(d)); gl.append(dict(key=k, bbox=bbox(d), x=x, adv=g['adv']))
        else:
            gl.append(dict(key=k, bbox=None, x=x, adv=g['adv']))
        x += g['adv'] + tracking
    p = U(parts)
    if th: p = thicken(p, th)
    p = P_simplify(P_from_d(smooth_adaptive(d_from_P(p), s2)))
    return p, gl

def seg(p, q, w0, w1, bow):
    """slightly bowed brush segment p->q (bow > 0 bulges up)."""
    nx, ny = (q[1] - p[1]), -(q[0] - p[0]); l = math.hypot(nx, ny); nx /= l; ny /= l
    if ny > 0: nx, ny = -nx, -ny
    c1 = (p[0] + (q[0] - p[0]) / 3 + nx * bow, p[1] + (q[1] - p[1]) / 3 + ny * bow)
    c2 = (p[0] + 2 * (q[0] - p[0]) / 3 + nx * bow, p[1] + 2 * (q[1] - p[1]) / 3 + ny * bow)
    return brush(bez_pts([p, c1, c2, q], 90), w0, w1)

def roof_shape(x0, x1, eave, pitch=ROOF_PITCH, w=STEM, bow=1.6, lift=3.0, apex_dx=0.0):
    """hand-drawn gable: two strokes of one pen meeting in a softly rounded ridge.
    Right stroke ends a touch higher and thinner (pen lifting off)."""
    ax = (x0 + x1) / 2 + apex_dx
    t = math.tan(math.radians(pitch))
    apex = eave - t * (ax - x0)
    left = seg((x0, eave), (ax, apex), w * 0.94, w * 1.04, bow)
    right = seg((ax, apex), (x1, eave - lift), w * 1.04, w * 0.86, bow)
    return U([left, right]), apex

def outline_points(p):
    fp = FlatPen(1.0); parse_path(d_from_P(p), fp)
    return [pt for c in fp.contours for pt in c]

def wordmark(keys=WORD, span=(0, 2), kern=KERN, tracking=TRACK, pitch=ROOF_PITCH, over=ROOF_OVER, gap=ROOF_GAP,
             w=STEM * ROOF_W, apex_dx=-2.0, min_eave=None):
    word, gl = script(keys, tracking=tracking, kern=kern)
    i0, i1 = span
    x0 = gl[i0]['bbox'][0] - over
    x1 = gl[i1]['bbox'][2] + over
    # eave: just clear of everything under the roof (the «д» hook decides it)
    t = math.tan(math.radians(pitch)); half = (w / 2) / math.cos(math.radians(pitch))
    ax = (x0 + x1) / 2 + apex_dx
    eave = 1e9
    for x, y in outline_points(word):
        if x0 <= x <= x1:
            dist = (x - x0) if x <= ax else (x1 - x) + 0.0
            # roof underside at x: eave - t*dist + half ; need y >= underside + gap
            eave = min(eave, y + t * dist - half - gap)
    if min_eave is not None: eave = min(eave, min_eave)
    rf, apex = roof_shape(x0, x1, eave, pitch, w, apex_dx=apex_dx)
    return word, rf, gl

def geist(text, size, wght=400, tracking=0.0):
    r = T(text, GE, size, {'wght': wght}, tracking)
    return r['d'], r

def open_counter(p, k_major=1.1, k_minor=2.0, dx=0.0, dy=0.0):
    """open up the smallest closed counter of p: scale it along its own axes (PCA), so a slanted
    slit becomes a rounder oval; dx/dy nudge it."""
    fp = FlatPen(0.5); parse_path(d_from_P(p), fp)
    def area(c):
        a = np.array(c); x, y = a[:, 0], a[:, 1]
        return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    cs = sorted(fp.contours, key=lambda c: abs(area(c)))
    hole = np.array(cs[0]); c = hole.mean(axis=0)
    q = hole - c
    ev, evec = np.linalg.eigh(np.cov(q.T))          # ascending: minor, major
    minor, major = evec[:, 0], evec[:, 1]
    a1 = q @ major; a2 = q @ minor
    h = c + np.outer(a1 * k_major, major) + np.outer(a2 * k_minor, minor) + np.array([dx, dy])
    d = 'M' + 'L'.join(f'{x:.2f} {y:.2f}' for x, y in h) + 'Z'
    hp = P_from_d(smooth_d(d, 2.0, 3.0))
    return P_diff(p, hp)

# ---------------------------------------------------------------- svg output
def fmt_svg(items, pad):
    """items: list of (d, fill). Shift so bbox starts at pad; returns svg string, (W, H)."""
    bbs = [bbox(d) for d, _ in items if d]
    x0 = min(b[0] for b in bbs); y0 = min(b[1] for b in bbs)
    x1 = max(b[2] for b in bbs); y1 = max(b[3] for b in bbs)
    W = x1 - x0 + 2 * pad; H = y1 - y0 + 2 * pad
    dx, dy = pad - x0, pad - y0
    body = ''.join(f'<path d="{move(d, dx, dy)}" fill="{f}"/>' for d, f in items if d)
    return svg((0, 0, round(W, 2), round(H, 2)), body), (W, H)

def rrect(W, H, R):
    C = R * 0.45
    return (f'M{r2(R)} 0H{r2(W-R)}C{r2(W-C)} 0 {r2(W)} {r2(C)} {r2(W)} {r2(R)}V{r2(H-R)}C{r2(W)} {r2(H-C)} {r2(W-C)} {r2(H)} {r2(W-R)} {r2(H)}'
            f'H{r2(R)}C{r2(C)} {r2(H)} 0 {r2(H-C)} 0 {r2(H-R)}V{r2(R)}C0 {r2(C)} {r2(C)} 0 {r2(R)} 0Z')

def write(name, s):
    with open(os.path.join(OUT, name), 'w') as fh:
        fh.write(s)
    print(f'{name:22s} {len(s)/1024:6.1f} KB')

# ---------------------------------------------------------------- mark
MARK_TH = 13.0; MARK_OVER = 25; MARK_GAP = 14; MARK_PITCH = 30; MARK_XS = 1.2; MARK_SHORT = True
MARK_CK = (1.15, 2.0, 0.0, 0.0); MARK_FILL = 0.70; MARK_DY = 0.0
MARK_RW = 15.5 + MARK_TH - 2   # roof weight = the letter's stroke

def mark_shapes():
    md, _ = script(['д'], th=MARK_TH, s2=3.0, dxs=MARK_XS, short_d=MARK_SHORT, kern={})
    md = open_counter(md, *MARK_CK)
    b = md.bounds
    w = MARK_RW
    x0 = b[0] - MARK_OVER; x1 = b[2] + MARK_OVER
    t = math.tan(math.radians(MARK_PITCH)); half = (w / 2) / math.cos(math.radians(MARK_PITCH))
    ax = (x0 + x1) / 2 - 2
    eave = 1e9
    for x, y in outline_points(md):
        dist = (x - x0) if x <= ax else (x1 - x)
        eave = min(eave, y + t * dist - half - MARK_GAP)
    mr, _ = roof_shape(x0, x1, eave, MARK_PITCH, w, bow=0.8, lift=2.0, apex_dx=-2)
    return md, mr

def build():
    word, rf, gl = wordmark()
    dW, dR = d_from_P(word), d_from_P(rf)
    pad = 8
    s, (W, H) = fmt_svg([(dW, INK), (dR, ROOF)], pad); write('lockup.svg', s)
    print('  lockup ratio %.2f  (h %.1f, x-height share %.2f)' % (W / H, H, 78 / H))
    s, _ = fmt_svg([(dW, CREAM), (dR, PEACH)], pad); write('lockup-inverse.svg', s)
    s, _ = fmt_svg([(dW, INK), (dR, INK)], pad); write('lockup-mono.svg', s)

    # ---------------- mark: «д» under its roof in an ink tile
    md, mr = mark_shapes()
    grp = P_union(md, mr)
    gb = grp.bounds
    S = 512
    sc = MARK_FILL * S / max(gb[2] - gb[0], gb[3] - gb[1])
    gcx = (gb[0] + gb[2]) / 2; gcy = (gb[1] + gb[3]) / 2
    def place(p):
        return xform(d_from_P(p), sc, 0, 0, sc, S / 2 - gcx * sc, S / 2 - gcy * sc + MARK_DY * S)
    tile = rrect(S, S, 0.225 * S)
    body = f'<path d="{tile}" fill="{INK}"/><path d="{place(md)}" fill="{CREAM}"/><path d="{place(mr)}" fill="{PEACH}"/>'
    write('mark.svg', svg((0, 0, S, S), body))
    gw, gh = gb[2] - gb[0], gb[3] - gb[1]; side = max(gw, gh) * 1.12
    dm = move(d_from_P(grp), side / 2 - (gb[0] + gb[2]) / 2, side / 2 - (gb[1] + gb[3]) / 2)
    write('mark-mono.svg', svg((0, 0, round(side, 2), round(side, 2)), f'<path d="{dm}" fill="{INK}"/>'))

    # ---------------- stacked: «дом» under the roof / «щенков.рф» / tagline, on an ink card
    w1, r1, g1 = wordmark(['д', 'о', 'м'], (0, 2), kern={1: -1})
    w2, g2 = script(['щ', 'е', 'н', 'к', 'о2', 'в', '.', 'р', 'ф'], kern={1: 1, 2: 1, 4: -2, 6: 4, 7: -2, 8: -1})
    b1 = w1.bounds; b2 = w2.bounds
    c1 = (b1[0] + b1[2]) / 2 + 3; c2 = (b2[0] + b2[2]) / 2 - 6     # optical centring (slant, «.рф» tail)
    line_gap = 146
    d1 = move(d_from_P(w1), -c1, 0); dr1 = move(d_from_P(r1), -c1, 0)
    d2 = move(d_from_P(w2), -c2, line_gap)
    tg, _ = geist('питомник щенков', 36, 400, 0.6)
    tb = bbox(tg)
    dtg = move(tg, -(tb[0] + tb[2]) / 2, line_gap + b2[3] + 64)
    items = [(d1, CREAM), (dr1, PEACH), (d2, CREAM), (dtg, MUTED_INV)]
    bbs = [bbox(d) for d, _ in items]
    x0 = min(b[0] for b in bbs); y0 = min(b[1] for b in bbs); x1 = max(b[2] for b in bbs); y1 = max(b[3] for b in bbs)
    side = max(x1 - x0, y1 - y0) * 1.28
    ox, oy = side / 2 - (x0 + x1) / 2, side / 2 - (y0 + y1) / 2 + 4
    body = f'<path d="{rrect(side, side, side * 0.16)}" fill="{INK}"/>' + ''.join(f'<path d="{move(d, ox, oy)}" fill="{f}"/>' for d, f in items)
    write('stacked.svg', svg((0, 0, round(side, 2), round(side, 2)), body))

    # ---------------- extra: round sticker «растим / дома» — the roof goes over the root «дом» of any word
    wa, _ = script(['р', 'а', 'с', 'т', 'и', 'м'], kern={3: -2, 4: 1})
    wb, rb, _ = wordmark(['д', 'о', 'м', 'а'], (0, 2), kern={1: -1, 3: -1})
    ba = wa.bounds; bbw = P_union(wb, rb).bounds; bw = wb.bounds
    ca = (ba[0] + ba[2]) / 2; cb = (bw[0] + bw[2]) / 2
    yb = ba[3] - bbw[1] + 26          # roof apex clears the descender of «р» by 26 u
    items = [(move(d_from_P(wa), -ca, 0), CREAM), (move(d_from_P(wb), -cb, yb), CREAM), (move(d_from_P(rb), -cb, yb), PEACH)]
    dom, _ = geist('домщенков.рф', 30, 400, 0.8)
    tb = bbox(dom); items.append((move(dom, -(tb[0] + tb[2]) / 2, yb + bw[3] + 70), MUTED_INV))
    bbs = [bbox(d) for d, _ in items]
    x0 = min(b[0] for b in bbs); y0 = min(b[1] for b in bbs); x1 = max(b[2] for b in bbs); y1 = max(b[3] for b in bbs)
    D = max(x1 - x0, y1 - y0) * 1.42
    ox, oy = D / 2 - (x0 + x1) / 2, D / 2 - (y0 + y1) / 2
    r_ = D / 2; k = 0.5523 * r_
    circ = (f'M{r2(r_)} 0C{r2(r_+k)} 0 {r2(D)} {r2(r_-k)} {r2(D)} {r2(r_)}C{r2(D)} {r2(r_+k)} {r2(r_+k)} {r2(D)} {r2(r_)} {r2(D)}'
            f'C{r2(r_-k)} {r2(D)} 0 {r2(r_+k)} 0 {r2(r_)}C0 {r2(r_-k)} {r2(r_-k)} 0 {r2(r_)} 0Z')
    body = f'<path d="{circ}" fill="{NAVY}"/>' + ''.join(f'<path d="{move(d, ox, oy)}" fill="{f}"/>' for d, f in items)
    write('extra-sticker.svg', svg((0, 0, round(D, 2), round(D, 2)), body))

    # ---------------- extra: puppy passport cover, filled in by hand
    PW, PH = 1050, 1480
    parts = [f'<path d="{rrect(PW, PH, 56)}" fill="{NAVY}"/>']
    lb = P_union(word, rf).bounds
    ls = 760 / (lb[2] - lb[0])
    lx = PW / 2 - (lb[0] + lb[2]) / 2 * ls; ly = 500 - lb[3] * ls
    parts.append(f'<path d="{xform(dW, ls, 0, 0, ls, lx, ly)}" fill="{CREAM}"/><path d="{xform(dR, ls, 0, 0, ls, lx, ly)}" fill="{PEACH}"/>')
    t1, _ = geist('паспорт щенка', 60, 400, 0.5); b_ = bbox(t1)
    parts.append(f'<path d="{move(t1, PW/2 - (b_[0]+b_[2])/2, 680)}" fill="{CREAM}"/>')
    t2, _ = geist('питомник щенков · москва', 36, 400, 0.4); b_ = bbox(t2)
    parts.append(f'<path d="{move(t2, PW/2 - (b_[0]+b_[2])/2, 738)}" fill="{NAVY_MUTED}"/>')
    ns = 0.6
    for label, keys, yy in [('кличка', ['п', 'е', 'р', 'с', 'и', 'к'], 1140), ('порода', ['м', 'а', 'л', 'ь', 'т', 'и', 'п', 'у'], 1290)]:
        lab, _ = geist(label, 36, 400, 0.4)
        parts.append(f'<path d="{move(lab, 150, yy)}" fill="{NAVY_MUTED}"/>')
        nm, _ = script(keys)
        nb = nm.bounds
        parts.append(f'<path d="{xform(d_from_P(nm), ns, 0, 0, ns, 330 - nb[0]*ns, yy)}" fill="{CREAM}"/>')
        parts.append(f'<path d="M150 {yy+38.5}H900V{yy+41}H150Z" fill="{NAVY_MUTED}"/>')
    write('extra-passport.svg', svg((0, 0, PW, PH), ''.join(parts)))


if __name__ == '__main__':
    build()
