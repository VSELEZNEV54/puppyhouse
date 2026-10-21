"""Geometry helpers for the «Пухлый» concept: text -> skia paths, thicken, booleans, SVG output."""
import math, os, re, sys
import pathops
from pathops import Path, LineCap, LineJoin

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import text2path  # noqa: E402  (read-only use of the shared tool)

FONTS = os.path.join(ROOT, 'fonts')
K = 0.5522847498  # cubic circle constant


def shape(font, text, size, var=None, tracking=0.0, x=0.0, y=0.0, features=None):
    return text2path.shape(os.path.join(FONTS, font), text, size, var or {}, tracking, features or [], x, y)


_tok = re.compile(r'[MLQCZ]|-?\d*\.?\d+(?:e-?\d+)?')


def d2path(d):
    p = Path()
    toks = _tok.findall(d)
    i = 0
    cmd = None
    while i < len(toks):
        t = toks[i]
        if t in 'MLQCZ':
            cmd = t; i += 1
            if cmd == 'Z':
                p.close(); continue
        n = {'M': 2, 'L': 2, 'Q': 4, 'C': 6}[cmd]
        v = [float(x) for x in toks[i:i + n]]; i += n
        if cmd == 'M': p.moveTo(*v)
        elif cmd == 'L': p.lineTo(*v)
        elif cmd == 'Q': p.quadTo(*v)
        elif cmd == 'C': p.cubicTo(*v)
    return p


class _Pen:
    def __init__(self, nd=2):
        self.s = []; self.nd = nd
    def f(self, v):
        r = round(v, self.nd)
        if r == 0: r = 0.0
        s = f"{r:.{self.nd}f}".rstrip('0').rstrip('.')
        return s if s not in ('-0', '') else '0'
    def P(self, pt): return f"{self.f(pt[0])} {self.f(pt[1])}"
    def moveTo(self, pt): self.s.append('M' + self.P(pt))
    def lineTo(self, pt): self.s.append('L' + self.P(pt))
    def curveTo(self, *pts):
        self.s.append('C' + ' '.join(self.P(p) for p in pts))
    def qCurveTo(self, *pts):
        # TrueType style: implied on-curve points between off-curves
        offs, end = pts[:-1], pts[-1]
        if end is None:
            raise ValueError('closed quad contours without on-curve not supported')
        for k, c in enumerate(offs):
            if k < len(offs) - 1:
                n = offs[k + 1]
                e = ((c[0] + n[0]) / 2, (c[1] + n[1]) / 2)
            else:
                e = end
            self.s.append('Q' + self.P(c) + ' ' + self.P(e))
    def closePath(self): self.s.append('Z')
    def endPath(self): pass
    def addComponent(self, *a): raise NotImplementedError


def path2d(p, nd=2):
    q = copy(p)
    q.convertConicsToQuads()
    pen = _Pen(nd)
    q.draw(pen)
    return ''.join(pen.s)


def copy(p):
    q = Path()
    q.addPath(p)
    return q


def _requant(p, nd=3):
    q = copy(p); q.convertConicsToQuads()
    pen = _Pen(nd); q.draw(pen)
    return d2path(''.join(pen.s))


def _op(a, b, kind):
    """pathops with fallbacks: skia occasionally refuses near-degenerate inputs"""
    try:
        return pathops.op(a, b, kind)
    except pathops.PathOpsError:
        pass
    for nd in (3, 2):
        try:
            return pathops.op(_requant(a, nd), _requant(b, nd), kind)
        except pathops.PathOpsError:
            continue
    return pathops.op(_requant(a, 2), translate(_requant(b, 2), 0.003, 0.002), kind)


def union(*ps):
    ps = [p for p in ps if p is not None]
    out = _op(ps[0], ps[0], pathops.PathOp.UNION) if len(ps) == 1 else None
    if out is None:
        out = ps[0]
        for p in ps[1:]:
            out = _op(out, p, pathops.PathOp.UNION)
    return out


def diff(a, b):
    return _op(a, b, pathops.PathOp.DIFFERENCE)


def inter(a, b):
    return _op(a, b, pathops.PathOp.INTERSECTION)


def simplify(p):
    return pathops.simplify(p)


def thicken(p, w):
    """Dilate a filled shape by w/2 with round joins (soft, puffy)."""
    if w <= 0: return simplify(p)
    s = copy(p)
    s.stroke(w, LineCap.ROUND_CAP, LineJoin.ROUND_JOIN, 4)
    s.convertConicsToQuads()
    return union(simplify(p), s)


def erode(p, w):
    """Shrink a filled shape by w/2 (round): box minus dilation of the complement."""
    l, t, r, b = p.bounds
    m = w * 2 + 10
    box = rect(l - m, t - m, r + m, b + m)
    comp = diff(box, p)
    comp = thicken(comp, w)
    return diff(box, comp)


def soften(p, r):
    """Round convex AND concave corners: close (dilate then erode) then open (erode then dilate)."""
    return thicken(erode(erode(thicken(p, 2 * r), 2 * r), 2 * r), 2 * r)


def rect(x0, y0, x1, y1):
    p = Path()
    p.moveTo(x0, y0); p.lineTo(x1, y0); p.lineTo(x1, y1); p.lineTo(x0, y1); p.close()
    return p


def rrect(x0, y0, x1, y1, r):
    p = Path()
    k = r * K
    p.moveTo(x0 + r, y0)
    p.lineTo(x1 - r, y0); p.cubicTo(x1 - r + k, y0, x1, y0 + r - k, x1, y0 + r)
    p.lineTo(x1, y1 - r); p.cubicTo(x1, y1 - r + k, x1 - r + k, y1, x1 - r, y1)
    p.lineTo(x0 + r, y1); p.cubicTo(x0 + r - k, y1, x0, y1 - r + k, x0, y1 - r)
    p.lineTo(x0, y0 + r); p.cubicTo(x0, y0 + r - k, x0 + r - k, y0, x0 + r, y0)
    p.close()
    return p


def squircle(x0, y0, x1, y1, r, smooth=0.75):
    """Rounded square with continuous-ish corners (iOS-like) using longer cubic handles."""
    p = Path()
    a = r * (1 + smooth * 0.6)  # corner extent along edge
    k1 = a * 0.62
    p.moveTo(x0 + a, y0)
    p.lineTo(x1 - a, y0); p.cubicTo(x1 - a + k1, y0, x1, y0 + a - k1, x1, y0 + a)
    p.lineTo(x1, y1 - a); p.cubicTo(x1, y1 - a + k1, x1 - a + k1, y1, x1 - a, y1)
    p.lineTo(x0 + a, y1); p.cubicTo(x0 + a - k1, y1, x0, y1 - a + k1, x0, y1 - a)
    p.lineTo(x0, y0 + a); p.cubicTo(x0, y0 + a - k1, x0 + a - k1, y0, x0 + a, y0)
    p.close()
    return p


def ellipse(cx, cy, rx, ry, rot=0.0):
    pts = []
    c, s = math.cos(rot), math.sin(rot)
    def T(x, y): return (cx + x * c - y * s, cy + x * s + y * c)
    p = Path()
    kx, ky = rx * K, ry * K
    p.moveTo(*T(rx, 0))
    p.cubicTo(*T(rx, ky), *T(kx, ry), *T(0, ry))
    p.cubicTo(*T(-kx, ry), *T(-rx, ky), *T(-rx, 0))
    p.cubicTo(*T(-rx, -ky), *T(-kx, -ry), *T(0, -ry))
    p.cubicTo(*T(kx, -ry), *T(rx, -ky), *T(rx, 0))
    p.close()
    return p


def circle(cx, cy, r):
    return ellipse(cx, cy, r, r)


def poly(pts):
    p = Path()
    p.moveTo(*pts[0])
    for q in pts[1:]: p.lineTo(*q)
    p.close()
    return p


def rounded_poly(pts, r):
    """Convex polygon with rounded corners of radius r (outer size kept = pts)."""
    # inset polygon by r then dilate by r
    n = len(pts)
    # compute inset via line offsets (polygon assumed clockwise in screen coords or ccw; detect)
    area = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2
    sgn = 1 if area > 0 else -1
    lines = []
    for i in range(n):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0; L = math.hypot(dx, dy)
        nx, ny = -dy / L * sgn, dx / L * sgn  # inward normal
        lines.append(((x0 + nx * r, y0 + ny * r), (dx, dy)))
    ins = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1[0] * d2[1] - d1[1] * d2[0]
        t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / den
        ins.append((p1[0] + d1[0] * t, p1[1] + d1[1] * t))
    return thicken(poly(ins), 2 * r)


def translate(p, dx, dy):
    return p.transform(1, 0, 0, 1, dx, dy)


def affine(p, a, b, c, d, e, f):
    return p.transform(a, b, c, d, e, f)


def scale(p, sx, sy=None, ox=0, oy=0):
    sy = sx if sy is None else sy
    return p.transform(sx, 0, 0, sy, ox - ox * sx, oy - oy * sy)


def contours(p):
    out = []
    for c in p.contours:
        out.append(c)
    return out


def bbox(p):
    return p.bounds


def svg(paths, viewbox, bg=None, extra=''):
    """paths: list of (Path|d, fill). viewbox: (x, y, w, h)."""
    x, y, w, h = [round(v, 2) for v in viewbox]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:g} {y:g} {w:g} {h:g}">']
    if bg:
        out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{bg}"/>')
    for p, fill in paths:
        d = p if isinstance(p, str) else path2d(p)
        out.append(f'<path d="{d}" fill="{fill}"/>')
    out.append(extra)
    out.append('</svg>')
    return '\n'.join(out) + '\n'
