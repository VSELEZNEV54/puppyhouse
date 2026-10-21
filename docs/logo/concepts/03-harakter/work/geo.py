"""Small vector geometry kit on top of skia-pathops (booleans, strokes) + text2path shaping.

All coordinates are SVG-style (y down). Paths are pathops.Path objects.
"""
import math, os, sys
import pathops
from pathops import Path, PathOp, LineCap, LineJoin, FillType
from fontTools.svgLib.path import parse_path

TOOLS = os.path.join(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..')), 'tools')
sys.path.insert(0, TOOLS)
import text2path  # noqa: E402

K = 0.5522847498  # cubic circle constant


# ---------- conversion ----------
def from_d(d):
    p = Path()
    pen = p.getPen()
    parse_path(d, pen)
    return p


def fmt(v):
    s = f"{v:.2f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def to_d(p):
    from fontTools.pens.svgPathPen import SVGPathPen
    pen = SVGPathPen(None, ntos=fmt)
    p.draw(pen)
    return pen.getCommands()


# ---------- booleans ----------
def union(*ps):
    ps = [p for p in ps if p is not None]
    if not ps:
        return Path()
    r = simplify(ps[0])
    for p in ps[1:]:
        r = pathops.op(r, p, PathOp.UNION, fix_winding=True)
    return r


def diff(a, *bs):
    r = a
    for b in bs:
        r = pathops.op(r, b, PathOp.DIFFERENCE, fix_winding=True)
    return r


def inter(a, b):
    return pathops.op(a, b, PathOp.INTERSECTION, fix_winding=True)


def simplify(p):
    return pathops.simplify(p, fix_winding=True)


def move(p, dx=0, dy=0):
    return p.transform(1, 0, 0, 1, dx, dy)


def scale(p, s, sy=None, cx=0, cy=0):
    sy = s if sy is None else sy
    return p.transform(s, 0, 0, sy, cx - s * cx, cy - sy * cy)


def rotate(p, deg, cx=0, cy=0):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return p.transform(c, s, -s, c, cx - c * cx + s * cy, cy - s * cx - c * cy)


def mirror_x(p, cx):
    return p.transform(-1, 0, 0, 1, 2 * cx, 0)


def bounds(p):
    return p.bounds  # (x0, y0, x1, y1)


# ---------- strokes ----------
def stroke(p, w, cap='round', join='round'):
    caps = dict(round=LineCap.ROUND_CAP, butt=LineCap.BUTT_CAP, square=LineCap.SQUARE_CAP)
    joins = dict(round=LineJoin.ROUND_JOIN, miter=LineJoin.MITER_JOIN, bevel=LineJoin.BEVEL_JOIN)
    q = Path()
    q.addPath(p)
    q.stroke(w, caps[cap], joins[join], 4)
    q.convertConicsToQuads(0.05)
    return simplify(q)


def embolden(p, amount):
    """grow a filled shape outward by `amount` with round joins"""
    if amount <= 0:
        return p
    return union(p, stroke(p, 2 * amount))


def shrink(p, amount, box=None):
    """inset a filled shape by `amount` (round joins)"""
    x0, y0, x1, y1 = p.bounds
    m = amount * 4 + 10
    frame = rect(x0 - m, y0 - m, x1 + m, y1 + m)
    outside = diff(frame, p)
    grown_out = embolden(outside, amount)
    return diff(p, grown_out)


# ---------- primitives ----------
def ellipse(cx, cy, rx, ry=None):
    ry = rx if ry is None else ry
    p = Path()
    pen = p.getPen()
    kx, ky = rx * K, ry * K
    pen.moveTo((cx + rx, cy))
    pen.curveTo((cx + rx, cy + ky), (cx + kx, cy + ry), (cx, cy + ry))
    pen.curveTo((cx - kx, cy + ry), (cx - rx, cy + ky), (cx - rx, cy))
    pen.curveTo((cx - rx, cy - ky), (cx - kx, cy - ry), (cx, cy - ry))
    pen.curveTo((cx + kx, cy - ry), (cx + rx, cy - ky), (cx + rx, cy))
    pen.closePath()
    return p


def circle(cx, cy, r):
    return ellipse(cx, cy, r, r)


def poly(pts):
    p = Path()
    pen = p.getPen()
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.closePath()
    return simplify(p)


def rect(x0, y0, x1, y1):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def rrect(x0, y0, x1, y1, r):
    """rounded rect with superellipse-ish (continuous) corners: cubic with 0.62 handles"""
    k = 0.4477  # smoother than circle (1-0.5523)
    p = Path()
    pen = p.getPen()
    pen.moveTo((x0 + r, y0))
    pen.lineTo((x1 - r, y0))
    pen.curveTo((x1 - r * k, y0), (x1, y0 + r * k), (x1, y0 + r))
    pen.lineTo((x1, y1 - r))
    pen.curveTo((x1, y1 - r * k), (x1 - r * k, y1), (x1 - r, y1))
    pen.lineTo((x0 + r, y1))
    pen.curveTo((x0 + r * k, y1), (x0, y1 - r * k), (x0, y1 - r))
    pen.lineTo((x0, y0 + r))
    pen.curveTo((x0, y0 + r * k), (x0 + r * k, y0), (x0 + r, y0))
    pen.closePath()
    return p


def squircle(cx, cy, half, r):
    return rrect(cx - half, cy - half, cx + half, cy + half, r)


def rounded_poly(pts, r):
    """convex/concave polygon with all corners rounded by r: inset polygon is given implicitly.
    pts = the corner points of the *final* outer polygon; we shrink then grow."""
    p = poly(pts)
    return embolden(shrink(p, r), r)


def tapered(c1, r1, c2, r2):
    """hull of two circles (a tapered capsule / teardrop)"""
    (x1, y1), (x2, y2) = c1, c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d <= abs(r1 - r2):
        return circle(x1, y1, max(r1, r2))
    ux, uy = dx / d, dy / d
    # angle of tangent normals
    a = math.acos((r1 - r2) / d)
    base = math.atan2(uy, ux)
    pts = []
    for sgn in (1, -1):
        t = base + sgn * a
        nx, ny = math.cos(t), math.sin(t)
        pts.append(((x1 + r1 * nx, y1 + r1 * ny), (x2 + r2 * nx, y2 + r2 * ny)))
    quad = poly([pts[0][0], pts[0][1], pts[1][1], pts[1][0]])
    return union(circle(x1, y1, r1), circle(x2, y2, r2), quad)


def cubic_path(p0, c1, c2, p1):
    p = Path()
    pen = p.getPen()
    pen.moveTo(p0)
    pen.curveTo(c1, c2, p1)
    pen.endPath()
    return p


def polyline(pts):
    p = Path()
    pen = p.getPen()
    pen.moveTo(pts[0])
    for q in pts[1:]:
        pen.lineTo(q)
    pen.endPath()
    return p


def bez_pts(p0, c1, c2, p1, n=40):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = mt ** 3 * p0[0] + 3 * mt * mt * t * c1[0] + 3 * mt * t * t * c2[0] + t ** 3 * p1[0]
        y = mt ** 3 * p0[1] + 3 * mt * mt * t * c1[1] + 3 * mt * t * t * c2[1] + t ** 3 * p1[1]
        out.append((x, y))
    return out


def tapered_stroke(pts, w0, w1, n_circles=None):
    """variable width stroke along a polyline: union of hulls between consecutive circles"""
    n = len(pts)
    parts = []
    for i in range(n - 1):
        t0, t1 = i / (n - 1), (i + 1) / (n - 1)
        r0 = (w0 + (w1 - w0) * t0) / 2
        r1 = (w0 + (w1 - w0) * t1) / 2
        parts.append(tapered(pts[i], r0, pts[i + 1], r1))
    return union(*parts)


# ---------- text ----------
FONTS = os.path.normpath(os.path.join(TOOLS, '..', 'fonts'))


def shape(font, text, size, var=None, tracking=0.0, kern=None, x=0.0, y=0.0, features=None):
    """returns list of dict(char, x, advance, path, bbox) with optional per-pair kerning tweaks.
    kern: dict index->dx applied before glyph index (cumulative)"""
    fp = font if os.path.exists(font) else os.path.join(FONTS, font)
    res = text2path.shape(fp, text, size, var or {}, tracking, features or [], 0.0, 0.0)
    glyphs = []
    shift = 0.0
    for i, g in enumerate(res['glyphs']):
        if kern and i in kern:
            shift += kern[i]
        p = from_d(g['d']) if g['d'] else Path()
        p = move(p, x + shift, y)
        glyphs.append(dict(char=g['char'], x=g['x'] + x + shift, advance=g['advance'], path=p,
                           bbox=p.bounds if g['d'] else None))
    meta = {k: res.get(k) for k in ('ascender', 'descender', 'xheight', 'capheight', 'advance')}
    meta['advance'] = (meta['advance'] or 0) + shift
    return glyphs, meta


def contours(p):
    """split a path into its contours (list of Paths)"""
    out = []
    cur = None
    for verb, pts in p.segments:
        if verb == 'moveTo':
            cur = Path()
            pen = cur.getPen()
            pen.moveTo(pts[0])
        elif verb == 'lineTo':
            for q in pts:
                pen.lineTo(q)
        elif verb == 'curveTo':
            pen.curveTo(*pts)
        elif verb == 'qCurveTo':
            pen.qCurveTo(*pts)
        elif verb == 'closePath':
            pen.closePath()
            out.append(cur)
        elif verb == 'endPath':
            pen.endPath()
            out.append(cur)
    return out


def area(p):
    return p.area


# ---------- svg ----------
def svg(view, layers, bg=None, rx=None):
    """layers: list of (path_or_d, fill). view: (x, y, w, h)"""
    x, y, w, h = view
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)}" width="{fmt(w)}" height="{fmt(h)}">']
    if bg:
        if rx:
            out.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="{fmt(rx)}" fill="{bg}"/>')
        else:
            out.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" fill="{bg}"/>')
    for p, fill in layers:
        d = p if isinstance(p, str) else to_d(p)
        if d:
            out.append(f'<path d="{d}" fill="{fill}"/>')
    out.append('</svg>')
    return '\n'.join(out) + '\n'
