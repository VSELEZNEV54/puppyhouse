import os
"""Small geometry helpers for the 05-rodnoj logo: text outlines, boolean ops, strokes, rounded polygons."""
import math, re, sys
import pathops
from fontTools.svgLib.path import parse_path
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, ROOT + '/tools')
from text2path import shape, resolve  # noqa: E402

GEIST = resolve('Geist[wght].ttf')


def P(d):
    """SVG path string -> pathops.Path"""
    p = pathops.Path()
    parse_path(d, p.getPen())
    return p


def D(path, nd=2):
    """pathops.Path -> compact SVG path string (coords rounded)."""
    pen = SVGPathPen(None, ntos=lambda v: fmt(v, nd))
    path.draw(pen)
    return pen.getCommands()


def fmt(v, nd=2):
    s = f"{round(v, nd):.{nd}f}".rstrip('0').rstrip('.')
    if s in ('-0', ''):
        s = '0'
    return s


def U(*paths):
    out = pathops.Path()
    items = []
    for p in paths:
        if isinstance(p, (list, tuple)):
            items += list(p)
        else:
            items.append(p)
    if not items:
        return out
    acc = items[0]
    for p in items[1:]:
        acc = pathops.op(acc, p, pathops.PathOp.UNION)
    return pathops.simplify(acc) if len(items) == 1 else acc


def SUB(a, b):
    return pathops.op(a, b, pathops.PathOp.DIFFERENCE)


def AND(a, b):
    return pathops.op(a, b, pathops.PathOp.INTERSECTION)


def T(path, a=1, b=0, c=0, d=1, e=0, f=0):
    """affine transform (SVG matrix order)"""
    out = pathops.Path()
    path.draw(TransformPen(out.getPen(), (a, b, c, d, e, f)))
    return out


def move(path, dx, dy):
    return T(path, 1, 0, 0, 1, dx, dy)


def scale(path, s, cx=0, cy=0):
    return T(path, s, 0, 0, s, cx - s * cx, cy - s * cy)


def stroke(path, w, cap='round', join='round'):
    p = pathops.Path()
    path.draw(p.getPen())
    capv = {'round': pathops.LineCap.ROUND_CAP, 'butt': pathops.LineCap.BUTT_CAP, 'square': pathops.LineCap.SQUARE_CAP}[cap]
    joinv = {'round': pathops.LineJoin.ROUND_JOIN, 'miter': pathops.LineJoin.MITER_JOIN, 'bevel': pathops.LineJoin.BEVEL_JOIN}[join]
    p.stroke(w, capv, joinv, 4)
    p.convertConicsToQuads()
    return pathops.simplify(p)


def open_path(d):
    """open (unfilled) centre-line path for stroking"""
    p = pathops.Path()
    parse_path(d, p.getPen())
    return p


def circle(cx, cy, r):
    k = 0.5523 * r
    return P(f"M{cx+r} {cy}C{cx+r} {cy+k} {cx+k} {cy+r} {cx} {cy+r}C{cx-k} {cy+r} {cx-r} {cy+k} {cx-r} {cy}"
             f"C{cx-r} {cy-k} {cx-k} {cy-r} {cx} {cy-r}C{cx+k} {cy-r} {cx+r} {cy-k} {cx+r} {cy}Z")


def ellipse(cx, cy, rx, ry, rot=0):
    kx, ky = 0.5523 * rx, 0.5523 * ry
    p = P(f"M{rx} 0C{rx} {ky} {kx} {ry} 0 {ry}C{-kx} {ry} {-rx} {ky} {-rx} 0C{-rx} {-ky} {-kx} {-ry} 0 {-ry}C{kx} {-ry} {rx} {-ky} {rx} 0Z")
    a = math.radians(rot)
    return T(p, math.cos(a), math.sin(a), -math.sin(a), math.cos(a), cx, cy)


def rrect(x, y, w, h, r):
    return rpoly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r)


def squircle(x, y, w, h, r, smooth=0.6):
    """rounded rect with continuous (iOS-like) corners: corner extends r*(1+smooth) along each edge"""
    e = r * (1 + smooth)
    k = r * (1 + smooth) * 0.62
    pts = []
    d = (f"M{x+e} {y}L{x+w-e} {y}C{x+w-e+k} {y} {x+w} {y+e-k} {x+w} {y+e}"
         f"L{x+w} {y+h-e}C{x+w} {y+h-e+k} {x+w-e+k} {y+h} {x+w-e} {y+h}"
         f"L{x+e} {y+h}C{x+e-k} {y+h} {x} {y+h-e+k} {x} {y+h-e}"
         f"L{x} {y+e}C{x} {y+e-k} {x+e-k} {y} {x+e} {y}Z")
    return P(d)


def rpoly(pts, radii):
    """closed polygon with circular fillets at each vertex (radius per vertex or one radius)"""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    segs = []
    for i in range(n):
        V = pts[i]; Pp = pts[i - 1]; N = pts[(i + 1) % n]
        r = radii[i]
        ax, ay = Pp[0] - V[0], Pp[1] - V[1]
        bx, by = N[0] - V[0], N[1] - V[1]
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        ax, ay, bx, by = ax / la, ay / la, bx / lb, by / lb
        cos_t = max(-1, min(1, ax * bx + ay * by))
        th = math.acos(cos_t)  # interior angle
        if r <= 0 or th < 1e-6 or abs(th - math.pi) < 1e-6:
            segs.append((V, V, V, V)); continue
        t = r / math.tan(th / 2)
        t = min(t, la * 0.5, lb * 0.5)
        r_eff = t * math.tan(th / 2)
        A = (V[0] + ax * t, V[1] + ay * t)
        B = (V[0] + bx * t, V[1] + by * t)
        phi = math.pi - th
        hl = 4 / 3 * math.tan(phi / 4) * r_eff
        C1 = (A[0] - ax * hl, A[1] - ay * hl)
        C2 = (B[0] - bx * hl, B[1] - by * hl)
        segs.append((A, C1, C2, B))
    d = f"M{segs[0][3][0]} {segs[0][3][1]}"
    for i in range(1, n + 1):
        A, C1, C2, B = segs[i % n]
        d += f"L{A[0]} {A[1]}"
        if A != B:
            d += f"C{C1[0]} {C1[1]} {C2[0]} {C2[1]} {B[0]} {B[1]}"
    d += "Z"
    return P(d)


def text(t, size, wght=500, tracking=0, x=0, y=0, font=None, kern=None):
    """Shape text; returns (list of glyph dicts with 'path'), info. kern: dict index->extra px before glyph i"""
    r = shape(font or GEIST, t, size, {'wght': wght}, tracking, None, 0, 0)
    gl = r['glyphs']
    shift = 0
    out = []
    for i, g in enumerate(gl):
        if kern and i in kern:
            shift += kern[i]
        p = move(P(g['d']), x + shift, y) if g['d'] else pathops.Path()
        b = g['bbox']
        out.append(dict(char=g['char'], x=g['x'] + x + shift, adv=g['advance'], path=p,
                        bbox=[b[0] + x + shift, b[1] + y, b[2] + x + shift, b[3] + y] if b else None))
    return out, r


def bounds(path):
    return path.bounds  # (xmin, ymin, xmax, ymax)


def svg(w, h, body, vb=None, bg=None):
    vb = vb or f"0 0 {fmt(w)} {fmt(h)}"
    bgr = f'<rect width="100%" height="100%" fill="{bg}"/>' if bg else ''
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{bgr}{body}</svg>\n'


def pathel(p, fill, extra=''):
    return f'<path fill="{fill}"{extra} d="{D(p)}"/>'
