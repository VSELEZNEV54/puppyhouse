"""Small vector-geometry kit on top of skia-pathops: primitives, rounded polygons,
boolean ops, SVG path parsing / writing. Coordinates: SVG (y down)."""
import math, re, json, subprocess, os
import pathops

K = 0.5522847498
HERE = os.path.dirname(os.path.abspath(__file__))
T2P = os.path.normpath(os.path.join(HERE, '..', '..', '..', 'tools', 'text2path.py'))


def new():
    return pathops.Path()


def ellipse(cx, cy, rx, ry, rot=0.0):
    """rotated ellipse as 4 cubics (rot in degrees, clockwise on screen)."""
    a = math.radians(rot)
    ca, sa = math.cos(a), math.sin(a)
    def T(x, y):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)
    p = new()
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


def rpoly(pts, r, smooth=1.0):
    """Polygon with rounded corners. r: number or list per vertex.
    smooth>1 stretches the corner (softer, squircle-like) while keeping it tangent."""
    n = len(pts)
    rs = r if isinstance(r, (list, tuple)) else [r] * n
    sm = smooth if isinstance(smooth, (list, tuple)) else [smooth] * n
    corners = []
    for i in range(n):
        A, V, B = pts[i - 1], pts[i], pts[(i + 1) % n]
        u1 = _unit(A[0] - V[0], A[1] - V[1]); u2 = _unit(B[0] - V[0], B[1] - V[1])
        dot = max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1]))
        th = math.acos(dot)
        if rs[i] <= 0 or th > math.pi - 1e-6:
            corners.append((V, V, V, V)); continue
        t = rs[i] / math.tan(th / 2) * sm[i]
        la = math.dist(A, V); lb = math.dist(B, V)
        t = min(t, la * 0.5, lb * 0.5) if sm[i] <= 1 else min(t, la * 0.499, lb * 0.499)
        phi = math.pi - th
        h = (4 / 3) * math.tan(phi / 4) * (t * math.tan(th / 2))  # radius-equivalent
        c = h / t if t else 0
        c = min(0.95, c * (1 + (sm[i] - 1) * 0.6))
        T1 = (V[0] + u1[0] * t, V[1] + u1[1] * t)
        T2 = (V[0] + u2[0] * t, V[1] + u2[1] * t)
        C1 = (T1[0] + (V[0] - T1[0]) * c, T1[1] + (V[1] - T1[1]) * c)
        C2 = (T2[0] + (V[0] - T2[0]) * c, T2[1] + (V[1] - T2[1]) * c)
        corners.append((T1, C1, C2, T2))
    p = new()
    p.moveTo(*corners[0][3])
    for i in range(1, n + 1):
        T1, C1, C2, T2 = corners[i % n]
        p.lineTo(*T1)
        if T1 != T2:
            p.cubicTo(*C1, *C2, *T2)
    p.close()
    return p


def rrect(x, y, w, h, r, smooth=1.0):
    return rpoly([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], r, smooth)


def _unit(x, y):
    l = math.hypot(x, y) or 1
    return (x / l, y / l)


def union(*ps):
    ps = [p for p in ps if p is not None]
    out = new()
    pathops.union(ps, out.getPen())
    return out


def diff(a, *bs):
    out = new()
    b = union(*bs)
    pathops.difference([a], [b], out.getPen())
    return out


def inter(a, b):
    out = new()
    pathops.intersection([a], [b], out.getPen())
    return out


def stroke(p, w, join='round', cap='round'):
    q = new(); q.addPath(p)
    J = {'round': pathops.LineJoin.ROUND_JOIN, 'miter': pathops.LineJoin.MITER_JOIN}[join]
    C = {'round': pathops.LineCap.ROUND_CAP, 'butt': pathops.LineCap.BUTT_CAP}[cap]
    q.stroke(w, C, J, 4)
    q.convertConicsToQuads(0.01)
    return union(q)


def grow(p, d):
    """offset outward by d (round joins)."""
    if d == 0:
        return union(p)
    return union(p, stroke(p, 2 * d))


def shrink(p, d):
    """offset inward by d."""
    if d == 0:
        return union(p)
    return diff(union(p), stroke(p, 2 * d))


def xf(p, a=1, b=0, c=0, d=1, e=0, f=0):
    """affine: x' = a x + c y + e ; y' = b x + d y + f"""
    return p.transform(a, b, c, d, e, f)


def move(p, dx, dy):
    return xf(p, 1, 0, 0, 1, dx, dy)


def scale(p, s, sy=None, ox=0, oy=0):
    sy = s if sy is None else sy
    return xf(p, s, 0, 0, sy, ox - ox * s, oy - oy * sy)


def rotate(p, deg, ox=0, oy=0):
    a = math.radians(deg); ca, sa = math.cos(a), math.sin(a)
    return xf(p, ca, sa, -sa, ca, ox - ox * ca + oy * sa, oy - ox * sa - oy * ca)


def mirror_x(p, cx):
    return xf(p, -1, 0, 0, 1, 2 * cx, 0)


def bounds(p):
    return p.bounds  # (x0, y0, x1, y1)


def fmt(v):
    s = f"{v:.2f}".rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def d(p):
    out = []
    pts = list(p.points); i = 0
    V = pathops.PathVerb
    for verb in p.verbs:
        if verb == V.MOVE:
            out.append('M' + fmt(pts[i][0]) + ' ' + fmt(pts[i][1])); i += 1
        elif verb == V.LINE:
            out.append('L' + fmt(pts[i][0]) + ' ' + fmt(pts[i][1])); i += 1
        elif verb == V.QUAD:
            out.append('Q' + ' '.join(fmt(c) for pt in pts[i:i + 2] for c in pt)); i += 2
        elif verb == V.CUBIC:
            out.append('C' + ' '.join(fmt(c) for pt in pts[i:i + 3] for c in pt)); i += 3
        elif verb == V.CLOSE:
            out.append('Z')
        else:
            raise ValueError(verb)
    return ''.join(out)


_tok = re.compile(r'[MLQCZmlqcz]|-?\d*\.?\d+(?:e-?\d+)?')


def parse(dstr):
    """absolute M L Q C Z only (what text2path emits)."""
    p = new()
    toks = _tok.findall(dstr)
    i = 0; cmd = None
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        t = toks[i]
        if t in 'MLQCZ':
            cmd = t; i += 1
            if cmd == 'Z':
                p.close(); continue
        if cmd == 'M':
            p.moveTo(num(), num()); cmd = 'L'
        elif cmd == 'L':
            p.lineTo(num(), num())
        elif cmd == 'Q':
            p.quadTo(num(), num(), num(), num())
        elif cmd == 'C':
            p.cubicTo(num(), num(), num(), num(), num(), num())
    return p


def text(font, txt, size, var=None, tracking=0, x=0, y=0, features=None):
    args = ['python3', T2P, '--font', font, '--text', txt, '--size', str(size), '--tracking', str(tracking),
            '--x', str(x), '--y', str(y)]
    for k, v in (var or {}).items():
        args += ['--var', f'{k}={v}']
    if features:
        args += ['--features', features]
    res = json.loads(subprocess.check_output(args))
    for g in res['glyphs']:
        g['path'] = parse(g['d'])
    res['path'] = parse(res['d'])
    return res


def svg(viewbox, body, extra=''):
    x, y, w, h = viewbox
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)}"{extra}>'
            + body + '</svg>\n')


def path_el(p, fill, extra=''):
    return f'<path d="{d(p)}" fill="{fill}"{extra}/>'


def egg(cx, cy, rx, ry_far, ry_near, rot=0.0):
    """egg: half-ellipse of ry_far on top (-y), ry_near on bottom; then rotated.
    rot=0 -> the 'far' (fat) end points up."""
    a = math.radians(rot); ca, sa = math.cos(a), math.sin(a)
    def T(x, y):
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)
    p = new()
    kx = rx * K
    p.moveTo(*T(rx, 0))
    p.cubicTo(*T(rx, ry_near * K), *T(kx, ry_near), *T(0, ry_near))
    p.cubicTo(*T(-kx, ry_near), *T(-rx, ry_near * K), *T(-rx, 0))
    p.cubicTo(*T(-rx, -ry_far * K), *T(-kx, -ry_far), *T(0, -ry_far))
    p.cubicTo(*T(kx, -ry_far), *T(rx, -ry_far * K), *T(rx, 0))
    p.close()
    return p


def aim(cx, cy, tx, ty):
    """rotation (deg) so that local 'up' points from (tx,ty) towards (cx,cy) -> away from target."""
    return math.degrees(math.atan2(cx - tx, -(cy - ty)))
