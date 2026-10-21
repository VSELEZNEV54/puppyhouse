"""Geometry + type helpers for 06-chetyre-porody (pathops booleans, text2path glyphs, SVG output)."""
import math, os, re, sys
import pathops
from pathops import Path, PathOp, LineCap, LineJoin

sys.dont_write_bytecode = True
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import text2path  # noqa: E402

K = 0.5522847498


def fmt(v):
    s = f"{v:.2f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


# ---------- primitives ----------
def ellipse(cx, cy, rx, ry, rot=0.0):
    p = Path()
    pts = []
    # 4 cubic arcs, then rotate
    c = [(cx + rx, cy), (cx, cy + ry), (cx - rx, cy), (cx, cy - ry)]
    p.moveTo(*c[0])
    p.cubicTo(cx + rx, cy + ry * K, cx + rx * K, cy + ry, cx, cy + ry)
    p.cubicTo(cx - rx * K, cy + ry, cx - rx, cy + ry * K, cx - rx, cy)
    p.cubicTo(cx - rx, cy - ry * K, cx - rx * K, cy - ry, cx, cy - ry)
    p.cubicTo(cx + rx * K, cy - ry, cx + rx, cy - ry * K, cx + rx, cy)
    p.close()
    if rot:
        p = rotate(p, rot, cx, cy)
    return p


def circle(cx, cy, r):
    return ellipse(cx, cy, r, r)


def rotate(p, deg, cx=0, cy=0):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    # translate(-c) rotate translate(+c)
    return p.transform(c, s, -s, c, cx - c * cx + s * cy, cy - s * cx - c * cy)


def move(p, dx, dy):
    return p.transform(1, 0, 0, 1, dx, dy)


def scale(p, sx, sy=None, cx=0, cy=0):
    sy = sx if sy is None else sy
    return p.transform(sx, 0, 0, sy, cx - sx * cx, cy - sy * cy)


def mirror_x(p, cx):
    return p.transform(-1, 0, 0, 1, 2 * cx, 0).reverse_copy() if False else _mirror(p, cx)


def _mirror(p, cx):
    q = p.transform(-1, 0, 0, 1, 2 * cx, 0)
    return q


def poly(points):
    p = Path()
    p.moveTo(*points[0])
    for pt in points[1:]:
        p.lineTo(*pt)
    p.close()
    return p


def rounded_poly(points, radii):
    """Convex/concave polygon with circular-ish (cubic) rounded corners. radii: number or list."""
    n = len(points)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    segs = []
    for i in range(n):
        p0 = points[i - 1]; p1 = points[i]; p2 = points[(i + 1) % n]
        v1 = (p0[0] - p1[0], p0[1] - p1[1]); v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*v1); l2 = math.hypot(*v2)
        u1 = (v1[0] / l1, v1[1] / l1); u2 = (v2[0] / l2, v2[1] / l2)
        cosang = max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1]))
        ang = math.acos(cosang)
        r = radii[i]
        t = r / math.tan(ang / 2) if r > 0 else 0
        t = min(t, l1 * 0.5, l2 * 0.5)
        r = t * math.tan(ang / 2)
        a = (p1[0] + u1[0] * t, p1[1] + u1[1] * t)
        b = (p1[0] + u2[0] * t, p1[1] + u2[1] * t)
        # cubic handle length for arc of sweep (pi - ang)
        sweep = math.pi - ang
        h = 4 / 3 * math.tan(sweep / 4) * r
        c1 = (a[0] - u1[0] * h, a[1] - u1[1] * h)
        c2 = (b[0] - u2[0] * h, b[1] - u2[1] * h)
        segs.append((a, c1, c2, b))
    p = Path()
    p.moveTo(*segs[0][3])
    for i in range(1, n + 1):
        a, c1, c2, b = segs[i % n]
        p.lineTo(*a)
        p.cubicTo(*c1, *c2, *b)
    p.close()
    return p


def rrect(x, y, w, h, r):
    return rounded_poly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r)


def superellipse(cx, cy, rx, ry, n=4.0, steps=96, rot=0):
    pts = []
    dense = 2400
    for i in range(dense):
        t = 2 * math.pi * i / dense
        c, s = math.cos(t), math.sin(t)
        x = cx + rx * math.copysign(abs(c) ** (2 / n), c)
        y = cy + ry * math.copysign(abs(s) ** (2 / n), s)
        pts.append((x, y))
    # start on the right-hand flat, uniform arc-length spacing -> even Catmull-Rom
    p = smooth_closed(resample(pts, steps))
    if rot:
        p = rotate(p, rot, cx, cy)
    return p


def smooth_closed(pts, tension=1.0):
    """Catmull-Rom through points -> closed cubic path."""
    n = len(pts)
    p = Path()
    p.moveTo(*pts[0])
    for i in range(n):
        p0 = pts[i - 1]; p1 = pts[i]; p2 = pts[(i + 1) % n]; p3 = pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6 * tension, p1[1] + (p2[1] - p0[1]) / 6 * tension)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6 * tension, p2[1] - (p3[1] - p1[1]) / 6 * tension)
        p.cubicTo(*c1, *c2, *p2)
    p.close()
    return p


# ---------- booleans ----------
def union(*ps):
    ps = [p for p in ps if p is not None]
    out = ps[0]
    for q in ps[1:]:
        out = pathops.op(out, q, PathOp.UNION)
    return out


def diff(a, *bs):
    for b in bs:
        a = pathops.op(a, b, PathOp.DIFFERENCE)
    return a


def inter(a, b):
    return pathops.op(a, b, PathOp.INTERSECTION)


def _stroke(p, w):
    q = Path(p)
    q.stroke(w, LineCap.ROUND_CAP, LineJoin.ROUND_JOIN, 4)
    q.convertConicsToQuads(0.02)
    return pathops.simplify(q)


def dilate(p, r):
    return union(p, _stroke(p, 2 * r))


def erode(p, r):
    return diff(p, _stroke(p, 2 * r))


def fillet(p, r):
    """round concave corners (closing)."""
    return erode(dilate(p, r), r)


def soften(p, r):
    """round convex corners (opening)."""
    return dilate(erode(p, r), r)


# ---------- svg output ----------
def to_d(p):
    out = []
    from pathops import PathVerb as V
    for verb, pts in p:
        if verb == V.MOVE:
            out.append(f"M{fmt(pts[0][0])} {fmt(pts[0][1])}")
        elif verb == V.LINE:
            out.append(f"L{fmt(pts[0][0])} {fmt(pts[0][1])}")
        elif verb == V.QUAD:
            out.append('Q' + ' '.join(f"{fmt(x)} {fmt(y)}" for x, y in pts))
        elif verb == V.CUBIC:
            out.append('C' + ' '.join(f"{fmt(x)} {fmt(y)}" for x, y in pts))
        elif verb == V.CLOSE:
            out.append('Z')
        else:
            raise ValueError(verb)
    return ''.join(out)


def bounds(p):
    return p.bounds  # (xmin, ymin, xmax, ymax)


# ---------- text ----------
TOK = re.compile(r'[MLQCZ]|-?\d+(?:\.\d+)?')


def d_to_path(d):
    toks = TOK.findall(d)
    p = Path(); i = 0; cmd = None; open_ = False
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        t = toks[i]
        if t in 'MLQCZ':
            cmd = t; i += 1
            if cmd == 'Z':
                p.close(); open_ = False
                continue
        if cmd == 'M':
            if open_:
                p.close()
            p.moveTo(num(), num()); open_ = True
        elif cmd == 'L':
            p.lineTo(num(), num())
        elif cmd == 'Q':
            p.quadTo(num(), num(), num(), num())
        elif cmd == 'C':
            p.cubicTo(num(), num(), num(), num(), num(), num())
    return p


def text(font, s, size, var=None, tracking=0.0, features=None, kern=None):
    """returns dict with 'path' (pathops, baseline y=0), glyph list (each with 'path'), metrics.
    kern: dict {index: extra_px} applied after glyph index (cumulative shift for following glyphs)."""
    res = text2path.shape(text2path.resolve(font), s, size, var or {}, tracking, features or [])
    shift = 0.0
    paths = []
    for gi, g in enumerate(res['glyphs']):
        gp = d_to_path(g['d']) if g['d'] else Path()
        if shift:
            gp = move(gp, shift, 0)
        g['path'] = gp
        g['x'] += shift
        if g['bbox']:
            g['bbox'] = [g['bbox'][0] + shift, g['bbox'][1], g['bbox'][2] + shift, g['bbox'][3]]
        paths.append(gp)
        if kern and gi in kern:
            shift += kern[gi]
    whole = Path()
    for gp in paths:
        whole.addPath(gp)
    res['path'] = whole
    res['advance'] += shift
    return res


def svg(view, body, w=None, h=None):
    x, y, vw, vh = view
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(x)} {fmt(y)} {fmt(vw)} {fmt(vh)}">' + body + '</svg>\n')


def pathel(p, fill, extra=''):
    d = to_d(p) if not isinstance(p, str) else p
    return f'<path d="{d}" fill="{fill}"{extra}/>'


def flatten(p, per_seg=24):
    """sample a single-contour path into points."""
    from pathops import PathVerb as V
    pts = []; cur = None; start = None
    for verb, ps in p:
        if verb == V.MOVE:
            cur = ps[0]; start = cur; pts.append(cur)
        elif verb == V.LINE:
            for i in range(1, per_seg + 1):
                t = i / per_seg
                pts.append((cur[0] + (ps[0][0] - cur[0]) * t, cur[1] + (ps[0][1] - cur[1]) * t))
            cur = ps[0]
        elif verb == V.QUAD:
            c, e = ps
            for i in range(1, per_seg + 1):
                t = i / per_seg; u = 1 - t
                pts.append((u*u*cur[0] + 2*u*t*c[0] + t*t*e[0], u*u*cur[1] + 2*u*t*c[1] + t*t*e[1]))
            cur = e
        elif verb == V.CUBIC:
            c1, c2, e = ps
            for i in range(1, per_seg + 1):
                t = i / per_seg; u = 1 - t
                pts.append((u**3*cur[0] + 3*u*u*t*c1[0] + 3*u*t*t*c2[0] + t**3*e[0], u**3*cur[1] + 3*u*u*t*c1[1] + 3*u*t*t*c2[1] + t**3*e[1]))
            cur = e
        elif verb == V.CLOSE:
            if start and cur != start:
                pts.append(start)
    if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        pts.pop()
    return pts


def resample(pts, n):
    import numpy as np
    P = np.array(pts + [pts[0]], dtype=float)
    seg = np.hypot(*(P[1:] - P[:-1]).T)
    L = np.concatenate([[0], np.cumsum(seg)])
    ts = np.linspace(0, L[-1], n, endpoint=False)
    x = np.interp(ts, L, P[:, 0]); y = np.interp(ts, L, P[:, 1])
    return list(zip(x, y))


def smooth_outline(p, n=360, sigma=7.0, out_n=72):
    """curvature-blending: resample by arc length, circular gaussian blur, refit with Catmull-Rom."""
    import numpy as np
    pts = np.array(resample(flatten(p), n))
    k = int(sigma * 3)
    w = np.exp(-0.5 * (np.arange(-k, k + 1) / sigma) ** 2); w /= w.sum()
    sm = np.zeros_like(pts)
    for i, wi in zip(range(-k, k + 1), w):
        sm += wi * np.roll(pts, i, axis=0)
    q = resample([tuple(v) for v in sm], out_n)
    return smooth_closed(q)
