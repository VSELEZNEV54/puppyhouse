"""Wordmark geometry for «Пухлый» v3: lowercase «домщенков» + «.рф» from Nunito outlines (no morphology),
a soft house with ONE trait standing inside the «о» of «дом», descriptor in Geist 500.

Units: the wordmark is set at size 100, baseline y = 0, y grows downward.
Every letter is the font's own hand-drawn outline; the only changes are explicit node edits
(points moved by a rule written below for each letter), so curves stay exactly as drawn.
"""
import math, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import *  # noqa

FONT = 'Nunito[wght].ttf'
TAGFONT = 'Geist[wght].ttf'

# ------------------------------------------------------------------ outline parsing / node edits
_tok = re.compile(r'[MLQCZ]|-?\d*\.?\d+(?:e-?\d+)?')


def parse_d(d):
    """SVG path (absolute M L Q C Z, as text2path writes it) -> [[(cmd, [(x, y), ...]), ...], ...]"""
    cs, cur, cmd, i = [], None, None, 0
    toks = _tok.findall(d)
    while i < len(toks):
        t = toks[i]
        if t in 'MLQCZ':
            cmd = t; i += 1
            if cmd == 'Z':
                if cur: cs.append(cur)
                cur = None
                continue
        n = {'M': 2, 'L': 2, 'Q': 4, 'C': 6}[cmd]
        v = [float(x) for x in toks[i:i + n]]; i += n
        pts = [(v[k], v[k + 1]) for k in range(0, n, 2)]
        if cmd == 'M':
            cur = [('M', pts)]
        else:
            cur.append((cmd, pts))
    if cur: cs.append(cur)
    return cs


def to_path(cs):
    p = Path()
    for c in cs:
        for cmd, pts in c:
            if cmd == 'M': p.moveTo(*pts[0])
            elif cmd == 'L': p.lineTo(*pts[0])
            elif cmd == 'Q': p.quadTo(*pts[0], *pts[1])
            elif cmd == 'C': p.cubicTo(*pts[0], *pts[1], *pts[2])
        p.close()
    return p


def move(cs, fn):
    """apply fn(x, y) -> (x, y) to every on- and off-curve point"""
    return [[(cmd, [fn(x, y) for x, y in pts]) for cmd, pts in c] for c in cs]


def tf(cs, k, dx, dy):
    return move(cs, lambda x, y: (x * k + dx, y * k + dy))


# ------------------------------------------------------------------ hand edits per letter (size-100 units)
# Counter bands of the Nunito letters (x ranges between the stems), used to squeeze a letter horizontally
# without touching its stems, joins or round ends.
BANDS = {'м': [(21.3, 50.0)], 'щ': [(22.3, 35.3), (51.4, 64.4)], 'н': [(23.4, 39.6)], 'д': [(27.4, 38.8)],
         'в': [(22.0, 33.0)], 'ф': [(21.5, 31.5), (57.0, 67.0)]}


def squeeze(cs, bands, s):
    """piecewise horizontal compression: inside each band x is scaled by s, everything right of it slides left.
    Stems keep their width; only counters get narrower. Returns (cs, total shift)."""
    def f(x, y):
        dx = 0.0
        for a, b in bands:
            if x >= b: dx += (b - a) * (1 - s)
            elif x > a: dx += (x - a) * (1 - s)
        return (x - dx, y)
    return move(cs, f), sum((b - a) * (1 - s) for a, b in bands)


def edit_letter(ch, cs, E):
    """E: {char: {edit: value}}. Every edit moves groups of points by a rule, so straight segments stay straight
    and the font's own corner curves keep their drawing (no offsets, no erosion, no booleans).
    Returns (cs, advance change)."""
    e = E.get(ch, {})
    da = 0.0
    if e.get('down'):                          # longer descender: everything below the baseline moves down
        k = e['down']
        cs = move(cs, lambda x, y: (x, y + k if y > 0.5 else y))
    if e.get('squeeze') and BANDS.get(ch):
        cs, sh = squeeze(cs, BANDS[ch], e['squeeze'])
        da -= sh
    return cs, da


# ------------------------------------------------------------------ clean corner fillets (no morphology)
class _Rec:
    """records a pathops path as contours of segments: ('L', P0, P1) or ('C', P0, C1, C2, P1)"""
    def __init__(self):
        self.cs, self.cur, self.p = [], None, None
    def moveTo(self, p):
        self.cur = []; self.p = p; self.start = p
    def lineTo(self, p):
        if math.dist(self.p, p) > 1e-6: self.cur.append(['L', self.p, p])
        self.p = p
    def curveTo(self, *pts):
        self.cur.append(['C', self.p, *pts]); self.p = pts[-1]
    def qCurveTo(self, *pts):
        offs, end = pts[:-1], pts[-1]
        p0 = self.p
        for k, c in enumerate(offs):
            e = ((c[0] + offs[k + 1][0]) / 2, (c[1] + offs[k + 1][1]) / 2) if k < len(offs) - 1 else end
            c1 = (p0[0] + 2 / 3 * (c[0] - p0[0]), p0[1] + 2 / 3 * (c[1] - p0[1]))
            c2 = (e[0] + 2 / 3 * (c[0] - e[0]), e[1] + 2 / 3 * (c[1] - e[1]))
            self.cur.append(['C', p0, c1, c2, e]); p0 = e
        self.p = end
    def closePath(self):
        if self.cur is not None:
            if math.dist(self.p, self.start) > 1e-6: self.cur.append(['L', self.p, self.start])
            self.cs.append(self.cur)
        self.cur = None
    endPath = closePath
    def addComponent(self, *a): raise NotImplementedError


def _unit(v):
    l = math.hypot(*v)
    return (v[0] / l, v[1] / l) if l > 1e-9 else (0.0, 0.0)


def _tan_end(s):
    if s[0] == 'L': return _unit((s[2][0] - s[1][0], s[2][1] - s[1][1]))
    for a in (s[3], s[2], s[1]):
        v = (s[4][0] - a[0], s[4][1] - a[1])
        if math.hypot(*v) > 1e-6: return _unit(v)
    return (0.0, 0.0)


def _tan_start(s):
    if s[0] == 'L': return _unit((s[2][0] - s[1][0], s[2][1] - s[1][1]))
    for a in (s[2], s[3], s[4]):
        v = (a[0] - s[1][0], a[1] - s[1][1])
        if math.hypot(*v) > 1e-6: return _unit(v)
    return (0.0, 0.0)


def _bez(s, t):
    p0, c1, c2, p1 = s[1], s[2], s[3], s[4]
    mt = 1 - t
    return (mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p1[0],
            mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p1[1])


def _split(s, t):
    p0, c1, c2, p1 = s[1], s[2], s[3], s[4]
    L = lambda a, b: (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
    a, b, c = L(p0, c1), L(c1, c2), L(c2, p1)
    d, e = L(a, b), L(b, c)
    f = L(d, e)
    return ['C', p0, a, d, f], ['C', f, e, c, p1]


def _seglen(s):
    if s[0] == 'L': return math.dist(s[1], s[2])
    pts = [_bez(s, i / 16) for i in range(17)]
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(16))


def _trim(s, ts, te):
    """cut ts (distance from the start point) and te (from the end point) off a segment"""
    if s[0] == 'L':
        p0, p1 = s[1], s[2]
        u = _unit((p1[0] - p0[0], p1[1] - p0[1]))
        return ['L', (p0[0] + u[0] * ts, p0[1] + u[1] * ts), (p1[0] - u[0] * te, p1[1] - u[1] * te)]
    def find(d, from_end):
        lo, hi = 0.0, 1.0
        ref = s[4] if from_end else s[1]
        for _ in range(40):
            mid = (lo + hi) / 2
            t = 1 - mid if from_end else mid
            if math.dist(_bez(s, t), ref) < d: lo = mid
            else: hi = mid
        return (1 - lo) if from_end else lo
    t1 = find(te, True) if te > 0 else 1.0
    t0 = find(ts, False) if ts > 0 else 0.0
    seg = s
    if t1 < 1.0:
        seg = _split(seg, t1)[0]
    if t0 > 0.0:
        seg = _split(seg, t0 / t1)[1]
    return seg


def _merge_tiny(c, tiny=1.6):
    """fold very short straight bits into the neighbouring curve when they run in the same direction"""
    out = list(c)
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i, s in enumerate(out):
            if s[0] == 'L' and _seglen(s) < tiny:
                n = out[(i + 1) % len(out)]
                pv = out[i - 1]
                u = _tan_start(s)
                if n[0] == 'C' and math.degrees(math.acos(max(-1, min(1, u[0] * _tan_start(n)[0] + u[1] * _tan_start(n)[1])))) < 12:
                    n = list(n); n[1] = s[1]; out[(i + 1) % len(out)] = n; del out[i]; changed = True; break
                if pv[0] == 'C' and math.degrees(math.acos(max(-1, min(1, u[0] * _tan_end(pv)[0] + u[1] * _tan_end(pv)[1])))) < 12:
                    pv = list(pv); pv[4] = s[2]; out[i - 1] = pv; del out[i]; changed = True; break
    return out


def fillet_corners(p, r_in, r_out=0.0, min_turn=18.0, r_by=None):
    """Round every sharp corner of the outline with a true circular-looking blend: concave corners (joins,
    crotches, counter corners) get r_in, convex ones r_out. r_by(x, y, concave) may return a radius for a
    particular corner (or None for the default). Segments are trimmed and a tangent cubic is inserted:
    the font's curves elsewhere are untouched."""
    rec = _Rec(); simplify(p).draw(rec)
    cs = [_merge_tiny(c) for c in rec.cs if c]
    if not cs: return p
    def area(c):
        pts = [s[1] for s in c]
        return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
    big = max(cs, key=lambda c: abs(area(c)))
    sgn = 1 if area(big) > 0 else -1
    out = Path()
    for c in cs:
        n = len(c)
        lens = [_seglen(s) for s in c]
        ts, te, blend = [0.0] * n, [0.0] * n, [None] * n
        for i in range(n):
            a, b = c[i - 1], c[i]                # corner at the end of a / start of b
            u, v = _tan_end(a), _tan_start(b)
            cross = u[0] * v[1] - u[1] * v[0]
            turn = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))
            if math.degrees(turn) < min_turn:
                continue
            if math.degrees(turn) > 125 and min(lens[i - 1], lens[i]) < 9:
                continue        # a deep notch where a round stem end meets a bowl («р», «ф», waist of «в»): drawn so, kept
            concave = (cross > 0) != (sgn > 0)
            r = r_in if concave else r_out
            if r_by:
                rr = r_by(b[1][0], b[1][1], concave)
                if rr is not None: r = rr
            if r <= 0: continue
            d = r * math.tan(turn / 2)
            d = min(d, lens[i - 1] * 0.45, lens[i] * 0.45)
            te[i - 1] = d; ts[i] = d; blend[i] = True
        segs = [_trim(c[i], ts[i], te[i]) for i in range(n)]
        start = segs[0][1]
        out.moveTo(*start)
        for i in range(n):
            s = segs[i]
            if i > 0 and blend[i]:
                A, B = segs[i - 1][-1], s[1]
                u, v = _tan_end(segs[i - 1]), _tan_start(s)
                ang = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))
                R = math.dist(A, B) / (2 * math.sin(ang / 2)) if ang > 1e-6 else 0
                h = 4 / 3 * math.tan(ang / 4) * R
                out.cubicTo(A[0] + u[0] * h, A[1] + u[1] * h, B[0] - v[0] * h, B[1] - v[1] * h, *B)
            if s[0] == 'L': out.lineTo(*s[2])
            else: out.cubicTo(*s[2], *s[3], *s[4])
        if blend[0]:
            A, B = segs[-1][-1], segs[0][1]
            u, v = _tan_end(segs[-1]), _tan_start(segs[0])
            ang = math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1])))
            R = math.dist(A, B) / (2 * math.sin(ang / 2)) if ang > 1e-6 else 0
            h = 4 / 3 * math.tan(ang / 4) * R
            out.cubicTo(A[0] + u[0] * h, A[1] + u[1] * h, B[0] - v[0] * h, B[1] - v[1] * h, *B)
        out.close()
    return simplify(out)


# ------------------------------------------------------------------ shapes
def rpoly(pts, radii):
    """Closed polygon with a circular fillet of its own radius at every corner (convex or concave)."""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    segs = []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        r = radii[i]
        ux, uy = p0[0] - p1[0], p0[1] - p1[1]; lu = math.hypot(ux, uy); ux, uy = ux / lu, uy / lu
        vx, vy = p2[0] - p1[0], p2[1] - p1[1]; lv = math.hypot(vx, vy); vx, vy = vx / lv, vy / lv
        cosang = max(-1.0, min(1.0, ux * vx + uy * vy))
        ang = math.acos(cosang)            # inner angle at the corner
        if r <= 0 or ang < 1e-3 or abs(ang - math.pi) < 1e-3:
            segs.append((p1, p1, None)); continue
        t = r / math.tan(ang / 2)
        t = min(t, lu * 0.5, lv * 0.5)
        a = (p1[0] + ux * t, p1[1] + uy * t)
        b = (p1[0] + vx * t, p1[1] + vy * t)
        turn = math.pi - ang
        k = 4.0 / 3.0 * math.tan(turn / 4) * (t * math.tan(ang / 2))   # handle length for the real radius
        c1 = (a[0] - ux * k, a[1] - uy * k)
        c2 = (b[0] - vx * k, b[1] - vy * k)
        segs.append((a, b, (c1, c2)))
    p = Path()
    p.moveTo(*segs[0][1])
    for i in range(1, n + 1):
        a, b, c = segs[i % n]
        p.lineTo(*a)
        if c:
            p.cubicTo(*c[0], *c[1], *b)
    p.close()
    return simplify(p)


def house(cx, base, w, wall, roof, H):
    """The soft house standing on y=base, centred on cx, with ONE trait (H['trait']):
    'chimney' - a short chimney on the right slope (the one in use);
    'ear' - a floppy puppy ear hanging beside a wall (tried in round 3 and rejected: at 64-180 px it reads as a drip
    or a leaf, at 16 px it disappears; see r3/ear-vs-chimney.png); None - plain house."""
    x0, x1 = cx - w / 2, cx + w / 2
    yw = base - wall          # top of the walls
    top = yw - roof
    rp, re_, rb = H['r_peak'], H['r_eave'], H['r_base']
    trait = H.get('trait')
    if trait == 'chimney':
        # chimney sits on the right slope; its outer side is plumb, its top is level
        f0, f1 = H.get('ch_at', (0.52, 0.80))          # where it leaves / meets the slope (0 = peak, 1 = eave)
        cw = H.get('ch_w', 0.17) * w
        ctop = top + H.get('ch_top', 0.12) * roof      # top of the chimney (from the peak, down)
        sx = lambda f: cx + (x1 - cx) * f
        sy = lambda f: top + (yw - top) * f
        a = (sx(f0), sy(f0))
        cxr = a[0] + cw
        fb = (cxr - cx) / (x1 - cx)
        b = (cxr, sy(fb))
        rc = H.get('r_ch', 1.0)
        pts = [(cx, top), a, (a[0], ctop), (cxr, ctop), b, (x1, yw), (x1, base), (x0, base), (x0, yw)]
        rr = [rp, H.get('r_ch_in', 0.8), rc, rc, H.get('r_ch_in', 0.8), re_, rb, rb, re_]
        return rpoly(pts, rr)
    if trait == 'ear':
        # ONE floppy puppy ear: the roof runs on past the wall and hangs down beside it as a soft teardrop,
        # parted from the wall by a slit. side = +1 right, -1 left (mirror).
        e = H.get('ear', {})
        sd = e.get('side', 1)
        g = e.get('gap', 0.06) * w            # slit between the wall and the ear
        ew = e.get('w', 0.24) * w             # ear width
        L = e.get('len', 0.85) * wall         # tip of the ear below the eave line
        tilt = e.get('tilt', 0.04) * w        # the tip swings out a little
        nk = e.get('notch', 0.10) * wall      # top of the slit (below the eave line)
        slope = (yw - top) / (w / 2)
        X = lambda dx: cx + sd * (w / 2 + dx)
        ex = g + ew * e.get('shoulder', 0.55)
        pts = [(cx, top),
               (X(ex), yw + slope * ex),                       # roof carried past the wall: the ear's shoulder
               (X(g + ew + tilt), yw + L * 0.62),              # outer side
               (X(g + ew * 0.5 + tilt), yw + L),               # tip
               (X(g), yw + L * 0.66),                          # inner side
               (X(g), yw + nk),                                # top of the slit
               (X(0), yw + nk),                                # wall
               (X(0), base), (cx - sd * w / 2, base), (cx - sd * w / 2, yw)]
        rr = [rp, ew * e.get('r_sh', 0.5), ew * 0.5, ew * 0.5, ew * 0.3, g * 0.45, g * 0.45, rb, rb, re_]
        if sd < 0:
            pts, rr = pts[::-1], rr[::-1]
        return rpoly(pts, rr)
    body = rpoly([(cx, top), (x1, yw), (x1, base), (x0, base), (x0, yw)], [rp, re_, rb, rb, re_])
    return body


# ------------------------------------------------------------------ letters
def split(p):
    """outer contours (as one solid) and holes of a glyph"""
    p = simplify(p)
    cs = list(p.contours)
    big = max(cs, key=lambda c: abs(c.area))
    outers = [simplify(c) for c in cs if c.clockwise == big.clockwise]
    holes = [simplify(c) for c in cs if c.clockwise != big.clockwise]
    return union(*outers), holes


def o_outer(p):
    cs = sorted(simplify(p).contours, key=lambda c: -abs(c.area))
    return simplify(cs[0])


def house_in_o(outer, H):
    ob = outer.bounds
    cx = (ob[0] + ob[2]) / 2 + H.get('dx', 0.0)
    ow, oh = ob[2] - ob[0], ob[3] - ob[1]
    base = ob[3] - oh * H['floor']
    return house(cx, base, ow * H['w'], oh * H['wall'], oh * H['roof'], H)


FILLET_AT = {}     # per-letter corner radii: {char: [((x0, y0, x1, y1), r), ...]} in letter units (set by build.py)


def _r_by(ch):
    rules = FILLET_AT.get(ch)
    if not rules:
        return None
    def f(x, y, concave):
        for (x0, y0, x1, y1), r in rules:
            if x0 <= x <= x1 and y0 <= y <= y1:
                return r
        return None
    return f


def run(text, size, wght, track, kern, E, x0=0.0, dy=0.0, fil=0.0):
    """set a run of letters from the font's outlines with hand edits; returns [(char, path, x)], end x"""
    g = shape(FONT, text, 100.0, {'wght': wght}, 0.0)['glyphs']
    k = size / 100.0
    x = x0
    out = []
    for i, G in enumerate(g):
        if i > 0:
            x += (track + kern.get(g[i - 1]['char'] + G['char'], 0.0))
        gx = G['x']
        cs = move(parse_d(G['d']), lambda px, py: (px - gx, py))      # letter in its own units, origin at 0
        cs, da = edit_letter(G['char'], cs, E)
        p = simplify(to_path(cs))
        if fil:
            p = fillet_corners(p, fil, r_by=_r_by(G['char']))            # soft joins, in letter units
        p = p.transform(k, 0, 0, k, x, dy)
        out.append((G['char'], p, x))
        x += (G['advance'] + da) * k
    return out, x


def wordmark(P):
    """dict(word=letters of «домщенков» (the «о» of «дом» is a solid pebble with the house cut out), o=pebble,
    house=house path, tailp=«.рф»)"""
    E = P.get('edits', {})
    letters, end = run('домщенков', 100.0, P['wght'], P['track'], P['kern'], E, fil=P.get('fillet', 0.0))
    ch, p, x = letters[1]
    outer = o_outer(p)
    hs = house_in_o(outer, P['house'])
    letters[1] = (ch, diff(outer, hs), x)
    T = P['tail']
    tail, _ = run('.рф', 100.0 * T, P['wght'] + P.get('tail_wght', 0), P['track'] * T, P['tail_kern'], E,
                  end + P['tail_gap'], P.get('tail_dy', 0.0), fil=P.get('fillet', 0.0))
    return dict(letters=letters, o=outer, house=hs, tail=tail,
                word=union(*[p for _, p, _ in letters]), tailp=union(*[p for _, p, _ in tail]))


def tagline(text, size, wght=500, track=0.0, font=TAGFONT):
    t = shape(font, text, size, {'wght': wght}, track)
    return simplify(d2path(t['d']))


def bounds_union(*ps):
    bs = [p.bounds for p in ps if p is not None]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def fmt(v):
    s = f"{round(v, 2):.2f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def svg_doc(layers, box, pad=0.0):
    x0, y0, x1, y1 = box
    vb = (x0 - pad, y0 - pad, (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(fmt(v) for v in vb)}">']
    for p, fill in layers:
        if p is None:
            continue
        out.append(f'<path d="{path2d(p)}" fill="{fill}"/>')
    out.append('</svg>')
    return '\n'.join(out) + '\n', vb
