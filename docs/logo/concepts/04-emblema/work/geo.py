"""Small geometry kit for the 04-emblema logo: pathops booleans, primitives, text on arcs.

Everything is a pathops.Path in SVG coordinates (y down).
"""
import math, os, sys
import pathops
from fontTools.svgLib.path import parse_path

TOOLS = os.path.join(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')), 'tools')
sys.path.insert(0, TOOLS)
from text2path import shape as _shape, resolve as _resolve  # noqa: E402

K = 0.5522847498  # circle kappa


# ---------- conversion ----------
def from_d(d):
    p = pathops.Path()
    parse_path(d, p.getPen())
    return p


def fmt(v):
    s = f"{v:.2f}".rstrip('0').rstrip('.')
    if s in ('-0', ''):
        s = '0'
    return s


def to_d(p):
    out = []
    for verb, pts in p.segments:
        if verb == 'moveTo':
            out.append('M' + ' '.join(fmt(c) for c in pts[0]))
        elif verb == 'lineTo':
            out.append('L' + ' '.join(fmt(c) for c in pts[0]))
        elif verb == 'qCurveTo':
            # pathops may give several off-curve points (TrueType style); expand to Q chains
            *offs, end = pts
            if end is None:
                # closed contour made only of off-curve points (TrueType): implied on-curves are midpoints
                offs = list(offs)
                n = len(offs)
                mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                out.append('M' + ' '.join(fmt(c) for c in mid(offs[-1], offs[0])))
                for i in range(n):
                    e = mid(offs[i], offs[(i + 1) % n])
                    out.append('Q' + ' '.join(fmt(v) for pt in (offs[i], e) for v in pt))
                continue
            if len(offs) == 1:
                out.append('Q' + ' '.join(fmt(c) for pt in (offs[0], end) for c in pt))
            else:
                for i in range(len(offs)):
                    c = offs[i]
                    e = end if i == len(offs) - 1 else ((offs[i][0] + offs[i + 1][0]) / 2, (offs[i][1] + offs[i + 1][1]) / 2)
                    out.append('Q' + ' '.join(fmt(v) for pt in (c, e) for v in pt))
        elif verb == 'curveTo':
            out.append('C' + ' '.join(fmt(c) for pt in pts for c in pt))
        elif verb == 'closePath':
            out.append('Z')
    return ''.join(out)


# ---------- booleans ----------
def _op(a, b, op):
    return pathops.op(a, b, op, fix_winding=True, keep_starting_points=False)


def union(*ps):
    ps = [p for p in ps if p is not None]
    if not ps:
        return pathops.Path()
    r = ps[0]
    for q in ps[1:]:
        r = _op(r, q, pathops.PathOp.UNION)
    return r


def diff(a, *bs):
    r = a
    for b in bs:
        r = _op(r, b, pathops.PathOp.DIFFERENCE)
    return r


def inter(a, b):
    return _op(a, b, pathops.PathOp.INTERSECTION)


def simplify(p):
    return pathops.simplify(p, fix_winding=True)


# ---------- transforms ----------
def T(p, a=1, b=0, c=0, d=1, e=0, f=0):
    return p.transform(a, b, c, d, e, f)


def move(p, dx, dy):
    return T(p, 1, 0, 0, 1, dx, dy)


def scale(p, s, sy=None, cx=0, cy=0):
    sy = s if sy is None else sy
    return T(p, s, 0, 0, sy, cx - s * cx, cy - sy * cy)


def rotate(p, deg, cx=0, cy=0):
    a = math.radians(deg)
    co, si = math.cos(a), math.sin(a)
    # translate(cx,cy) rotate translate(-cx,-cy)
    return T(p, co, si, -si, co, cx - co * cx + si * cy, cy - si * cx - co * cy)


def mirror_x(p, cx):
    return T(p, -1, 0, 0, 1, 2 * cx, 0)


# ---------- primitives ----------
def ellipse(cx, cy, rx, ry=None):
    ry = rx if ry is None else ry
    p = pathops.Path()
    kx, ky = rx * K, ry * K
    p.moveTo(cx + rx, cy)
    p.cubicTo(cx + rx, cy + ky, cx + kx, cy + ry, cx, cy + ry)
    p.cubicTo(cx - kx, cy + ry, cx - rx, cy + ky, cx - rx, cy)
    p.cubicTo(cx - rx, cy - ky, cx - kx, cy - ry, cx, cy - ry)
    p.cubicTo(cx + kx, cy - ry, cx + rx, cy - ky, cx + rx, cy)
    p.close()
    return p


circle = ellipse


def rect(x, y, w, h):
    p = pathops.Path()
    p.moveTo(x, y); p.lineTo(x + w, y); p.lineTo(x + w, y + h); p.lineTo(x, y + h); p.close()
    return p


def poly(pts):
    p = pathops.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    p.close()
    return p


def rounded_poly(pts, radii):
    """Polygon with each corner rounded by a circular-ish (cubic) fillet of given radius."""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    p = pathops.Path()
    segs = []
    for i in range(n):
        P0, P1, P2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        r = radii[i]
        v1 = (P0[0] - P1[0], P0[1] - P1[1]); l1 = math.hypot(*v1)
        v2 = (P2[0] - P1[0], P2[1] - P1[1]); l2 = math.hypot(*v2)
        u1 = (v1[0] / l1, v1[1] / l1); u2 = (v2[0] / l2, v2[1] / l2)
        cosang = max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1]))
        ang = math.acos(cosang)
        if r <= 0 or ang < 1e-6:
            segs.append((P1, P1, P1, P1)); continue
        t = r / math.tan(ang / 2)
        t = min(t, l1 * 0.5, l2 * 0.5)
        A = (P1[0] + u1[0] * t, P1[1] + u1[1] * t)
        B = (P1[0] + u2[0] * t, P1[1] + u2[1] * t)
        # handle length for a circular arc of sweep (pi - ang)
        sweep = math.pi - ang
        h = 4 / 3 * math.tan(sweep / 4) * (t * math.tan(ang / 2))
        c1 = (A[0] - u1[0] * h, A[1] - u1[1] * h)
        c2 = (B[0] - u2[0] * h, B[1] - u2[1] * h)
        segs.append((A, c1, c2, B))
    p.moveTo(*segs[0][3])
    for i in range(1, n + 1):
        A, c1, c2, B = segs[i % n]
        p.lineTo(*A)
        if A != B:
            p.cubicTo(*c1, *c2, *B)
    p.close()
    return p


def rrect(x, y, w, h, r):
    return rounded_poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r)


def stroke_path(p, width, cap='round', join='round'):
    q = pathops.Path(p)
    caps = dict(round=pathops.LineCap.ROUND_CAP, butt=pathops.LineCap.BUTT_CAP, square=pathops.LineCap.SQUARE_CAP)
    joins = dict(round=pathops.LineJoin.ROUND_JOIN, miter=pathops.LineJoin.MITER_JOIN, bevel=pathops.LineJoin.BEVEL_JOIN)
    q.stroke(width, caps[cap], joins[join], 4)
    q.convertConicsToQuads()
    return simplify(q)


def polyline(pts):
    p = pathops.Path()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    return p


def ring(cx, cy, r_out, r_in):
    return diff(circle(cx, cy, r_out), circle(cx, cy, r_in))


def bbox(p):
    return p.bounds  # (xmin, ymin, xmax, ymax)


# ---------- text ----------
def text(font, txt, size, var=None, tracking=0.0, features=None):
    return _shape(_resolve(font), txt, size, var or {}, tracking, features or [])


def text_path(font, txt, size, var=None, tracking=0.0, x=0, y=0, kern=None):
    """Whole line as one Path; kern = {index: extra px after glyph i}."""
    res = text(font, txt, size, var, tracking)
    p = pathops.Path()
    shift = 0
    for i, g in enumerate(res['glyphs']):
        if g['d']:
            p = union(p, move(from_d(g['d']), x + shift, y))
        if kern and i in kern:
            shift += kern[i]
    return p, res


def arc_text(font, txt, size, var, cx, cy, r_mid, where='top', tracking=0.0, center_deg=0.0, kern=None, xh=None):
    """Set text along a circle.
    top: glyph baselines at r_mid - xh/2 (letters grow outward), reads clockwise.
    bottom: baselines at r_mid + xh/2 (letters grow inward), reads left-to-right upright.
    Angles from glyph centres (x + adv/2) along r_mid, evenly by advance.
    Returns (Path, total_angle_deg)."""
    res = text(font, txt, size, var, tracking)
    if xh is None:
        xh = res.get('xheight') or size * 0.5
    glyphs = res['glyphs']
    pos = []
    s = 0
    for i, g in enumerate(glyphs):
        pos.append(s + g['advance'] / 2)
        s += g['advance'] + ((kern or {}).get(i, 0))
    total = s - tracking
    out = pathops.Path()
    for g, c in zip(glyphs, pos):
        if not g['d']:
            continue
        gp = from_d(g['d'])
        gc = g['x'] + g['advance'] / 2
        sarc = c - total / 2
        th = sarc / r_mid + math.radians(center_deg)
        if where == 'top':
            rb = r_mid - xh / 2
            gp = move(gp, -gc, 0)
            gp = rotate(gp, math.degrees(th))
            gp = move(gp, cx + rb * math.sin(th), cy - rb * math.cos(th))
        else:
            rb = r_mid + xh / 2
            gp = move(gp, -gc, 0)
            gp = rotate(gp, -math.degrees(th))
            gp = move(gp, cx + rb * math.sin(th), cy + rb * math.cos(th))
        out = union(out, gp)
    return out, math.degrees(total / r_mid)


# ---------- svg ----------
def svg(view, layers, bg=None, rx=None):
    """view=(x,y,w,h); layers=[(Path or d, fill)]"""
    x, y, w, h = view
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)}">']
    if bg:
        if rx:
            parts.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{fmt(rx)}" fill="{bg}"/>')
        else:
            parts.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{bg}"/>')
    for p, fill in layers:
        d = p if isinstance(p, str) else to_d(p)
        if d:
            parts.append(f'<path d="{d}" fill="{fill}"/>')
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


def taper(c1, r1, c2, r2, n=8):
    """Convex hull of two circles (a tapered capsule) built from cubic arcs."""
    (x1, y1), (x2, y2) = c1, c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    base = math.atan2(dy, dx)
    # angle of tangent normal relative to the centre line
    a = math.acos(max(-1, min(1, (r1 - r2) / d)))
    p = pathops.Path()

    def arcpts(cx, cy, r, t0, t1, steps):
        pts = []
        for i in range(steps):
            ta = t0 + (t1 - t0) * i / steps
            tb = t0 + (t1 - t0) * (i + 1) / steps
            h = 4 / 3 * math.tan((tb - ta) / 4) * r
            A = (cx + r * math.cos(ta), cy + r * math.sin(ta))
            B = (cx + r * math.cos(tb), cy + r * math.sin(tb))
            cA = (A[0] - h * math.sin(ta), A[1] + h * math.cos(ta))
            cB = (B[0] + h * math.sin(tb), B[1] - h * math.cos(tb))
            pts.append((A, cA, cB, B))
        return pts
    # big arc around circle 2 from base-a to base+a (through base), then around circle 1 from base+a to base+2pi-a
    s2 = arcpts(x2, y2, r2, base - a, base + a, 4)
    s1 = arcpts(x1, y1, r1, base + a, base + 2 * math.pi - a, 6)
    p.moveTo(*s2[0][0])
    for A, cA, cB, B in s2:
        p.cubicTo(*cA, *cB, *B)
    p.lineTo(*s1[0][0])
    for A, cA, cB, B in s1:
        p.cubicTo(*cA, *cB, *B)
    p.close()
    return p


# ---------- smooth sweeps ----------
def resample_closed(pts, step):
    """resample a closed polyline at ~equal arc length"""
    P = pts + [pts[0]]
    L = [0.0]
    for i in range(1, len(P)):
        L.append(L[-1] + math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1]))
    total = L[-1]
    n = max(8, int(round(total / step)))
    out = []
    j = 0
    for k in range(n):
        s = total * k / n
        while L[j + 1] < s:
            j += 1
        seg = L[j + 1] - L[j]
        u = 0 if seg == 0 else (s - L[j]) / seg
        out.append((P[j][0] + (P[j + 1][0] - P[j][0]) * u, P[j][1] + (P[j + 1][1] - P[j][1]) * u))
    return out


def smooth_closed(pts, step=3.0):
    """closed Catmull-Rom spline through resampled points, as cubic Beziers"""
    Q = resample_closed(pts, step)
    n = len(Q)
    p = pathops.Path()
    p.moveTo(*Q[0])
    for i in range(n):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[(i + 1) % n], Q[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        p.cubicTo(*c1, *c2, *p2)
    p.close()
    return p


def sweep(spine, radius, n=400, step=2.5):
    """Outline of a circle of radius radius(t) swept along spine(t), t in [0,1], round caps.
    Returns a smooth closed Path."""
    C = [spine(i / n) for i in range(n + 1)]
    R = [radius(i / n) for i in range(n + 1)]
    left, right = [], []
    for i in range(n + 1):
        a, b = max(0, i - 1), min(n, i + 1)
        dx, dy = C[b][0] - C[a][0], C[b][1] - C[a][1]
        ds = math.hypot(dx, dy)
        Tx, Ty = dx / ds, dy / ds
        Nx, Ny = -Ty, Tx
        k = (R[b] - R[a]) / ds
        k = max(-0.95, min(0.95, k))
        q = math.sqrt(1 - k * k)
        r = R[i]
        left.append((C[i][0] + r * (-k * Tx + q * Nx), C[i][1] + r * (-k * Ty + q * Ny)))
        right.append((C[i][0] + r * (-k * Tx - q * Nx), C[i][1] + r * (-k * Ty - q * Ny)))
    def cap(cx, cy, r, p_from, p_to, through):
        a0 = math.atan2(p_from[1] - cy, p_from[0] - cx)
        a1 = math.atan2(p_to[1] - cy, p_to[0] - cx)
        am = math.atan2(through[1], through[0])
        # choose direction that passes through 'through' direction
        def norm(a):
            while a < 0: a += 2 * math.pi
            while a >= 2 * math.pi: a -= 2 * math.pi
            return a
        d_ccw = norm(a1 - a0)
        if norm(am - a0) <= d_ccw:
            sweep_a = d_ccw
        else:
            sweep_a = d_ccw - 2 * math.pi
        m = 40
        return [(cx + r * math.cos(a0 + sweep_a * j / m), cy + r * math.sin(a0 + sweep_a * j / m)) for j in range(1, m)]
    # end cap around C[n] from left[n] to right[n] through +T
    dx, dy = C[n][0] - C[n - 1][0], C[n][1] - C[n - 1][1]
    end = cap(C[n][0], C[n][1], R[n], left[n], right[n], (dx, dy))
    dx, dy = C[0][0] - C[1][0], C[0][1] - C[1][1]
    start = cap(C[0][0], C[0][1], R[0], right[0], left[0], (dx, dy))
    outline = left + end + right[::-1] + start
    return smooth_closed(outline, step)


def bez(p0, p1, p2, p3):
    def f(t):
        u = 1 - t
        return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])
    return f


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


# ---------- spines defined by curvature (one smooth curve, no kinks) ----------
def curv_knots(start, heading, knots, L, n=2000):
    """Spine from a curvature profile. knots = [(s, k), ...]: arc length s and curvature k
    (1/units; negative turns clockwise on screen). Curvature is 0 before the first knot and eased
    between knots with smoothstep, so tangent AND curvature are continuous: no kink anywhere.
    Returns (points, final heading in degrees)."""
    def kap(s):
        if s <= knots[0][0]:
            return knots[0][1]
        for (s0, k0), (s1, k1) in zip(knots, knots[1:]):
            if s <= s1:
                return k0 + (k1 - k0) * smoothstep(s0, s1, s)
        return knots[-1][1]
    th = math.radians(heading)
    x, y = start
    pts = [start]
    ds = L / n
    for i in range(n):
        s = (i + 0.5) * ds
        th += kap(s) * ds
        x += math.cos(th) * ds
        y += math.sin(th) * ds
        pts.append((x, y))
    return pts, math.degrees(th)


def polyfunc(pts):
    """dense polyline -> f(t), t in [0, 1], uniform in index (= arc length for curv_knots)."""
    n = len(pts) - 1
    def f(t):
        u = t * n
        i = min(n - 1, int(u))
        a = u - i
        return (pts[i][0] + (pts[i + 1][0] - pts[i][0]) * a, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * a)
    return f
