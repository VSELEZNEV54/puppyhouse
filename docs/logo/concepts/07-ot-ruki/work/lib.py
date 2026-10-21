import sys, os, re, math
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from text2path import shape, resolve
from fontTools.svgLib.path import parse_path
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen

def T(text, font, size, var=None, tracking=0.0, features=None):
    return shape(resolve(font), text, size, var or {}, tracking, features or [])

class _GS:
    def __init__(self): self.glyphs = {}

def xform(d, a=1, b=0, c=0, dd=1, e=0, f=0):
    """apply affine matrix (a b c d e f) to path d"""
    pen = SVGPathPen(None, ntos=lambda v: ('%.2f' % v).rstrip('0').rstrip('.') if '.' in ('%.2f' % v) else '%.2f' % v)
    tp = TransformPen(pen, (a, b, c, dd, e, f))
    parse_path(d, tp)
    return pen.getCommands()

def move(d, dx, dy, s=1.0):
    return xform(d, s, 0, 0, s, dx, dy)

def bbox(d):
    bp = BoundsPen(None)
    parse_path(d, bp)
    return bp.bounds

def r2(v):
    s = '%.2f' % v
    s = s.rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s

def svg(vb, body):
    x, y, w, h = vb
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{r2(x)} {r2(y)} {r2(w)} {r2(h)}">'
            + body + '</svg>\n')

import uharfbuzz as hb
from text2path import PathPen
_fonts = {}
def hbfont(font, var=None):
    key = (font, tuple(sorted((var or {}).items())))
    if key not in _fonts:
        blob = hb.Blob.from_file_path(resolve(font)); face = hb.Face(blob); f = hb.Font(face)
        if var: f.set_variations(var)
        _fonts[key] = (f, face.upem)
    return _fonts[key]

def G(font, name, size, var=None, x=0.0, y=0.0):
    """one glyph by glyph name (or char), drawn at origin x,y (baseline). returns dict(d, adv, bbox)"""
    f, upem = hbfont(font, var)
    s = size / upem
    if len(name) == 1:
        gid = f.get_nominal_glyph(ord(name))
    else:
        gid = f.get_glyph_from_name(name)
        if gid is None: gid = f.get_glyph_from_name(name.split('.')[0])
    pen = PathPen(s, x, y)
    f.draw_glyph_with_pen(gid, pen)
    return dict(d=pen.d(), adv=f.get_glyph_h_advance(gid) * s, bbox=pen.bbox(), x=x)

def shape_lang(font, text, size, var=None, lang=None, features=None):
    f, upem = hbfont(font, var)
    s = size / upem
    buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
    if lang: buf.language = lang
    hb.shape(f, buf, features or {})
    out = []; px = 0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        out.append((f.glyph_to_string(info.codepoint), px))
        px += pos.x_advance * s
    return out

import pathops
import numpy as np

def P_from_d(d):
    p = pathops.Path(); parse_path(d, p.getPen()); return p

def d_from_P(p):
    pen = SVGPathPen(None, ntos=r2); p.draw(pen); return pen.getCommands()

def P_union(*ps):
    ps = [p for p in ps if p is not None]
    return pathops.op(ps[0], ps[1], pathops.PathOp.UNION) if len(ps) == 2 else _uni(ps)

def _uni(ps):
    acc = ps[0]
    for p in ps[1:]:
        acc = pathops.op(acc, p, pathops.PathOp.UNION)
    return acc

def P_diff(a, b): return pathops.op(a, b, pathops.PathOp.DIFFERENCE)
def P_inter(a, b): return pathops.op(a, b, pathops.PathOp.INTERSECTION)

def P_simplify(p):
    q = pathops.Path(); p.draw(q.getPen()); return pathops.simplify(q)

def stroke_path(d, width, cap='round', join='round'):
    p = pathops.Path(); parse_path(d, p.getPen())
    caps = {'round': pathops.LineCap.ROUND_CAP, 'butt': pathops.LineCap.BUTT_CAP, 'square': pathops.LineCap.SQUARE_CAP}
    joins = {'round': pathops.LineJoin.ROUND_JOIN, 'miter': pathops.LineJoin.MITER_JOIN, 'bevel': pathops.LineJoin.BEVEL_JOIN}
    p.stroke(width, caps[cap], joins[join], 4)
    p.convertConicsToQuads(0.05)
    return pathops.simplify(p)

def rect_P(x0, y0, x1, y1):
    return P_from_d(f'M{x0} {y0}L{x1} {y0}L{x1} {y1}L{x0} {y1}Z')

def thicken(p, w):
    """outward offset by w/2 with round joins: union(fill, stroke(w))"""
    q = pathops.Path(); p.draw(q.getPen())
    q.stroke(w, pathops.LineCap.ROUND_CAP, pathops.LineJoin.ROUND_JOIN, 4)
    q.convertConicsToQuads(0.05)
    return P_union(pathops.simplify(q), p)

from fontTools.pens.basePen import BasePen

class FlatPen(BasePen):
    def __init__(self, step=0.5):
        super().__init__(None); self.contours = []; self.cur = None; self.step = step
    def _moveTo(self, p):
        self.cur = [p]; self.contours.append(self.cur)
    def _lineTo(self, p):
        a = self.cur[-1]; n = max(1, int(math.hypot(p[0]-a[0], p[1]-a[1]) / self.step))
        for i in range(1, n+1):
            t = i/n; self.cur.append((a[0]+(p[0]-a[0])*t, a[1]+(p[1]-a[1])*t))
    def _curveToOne(self, c1, c2, p):
        a = self.cur[-1]
        L = math.hypot(c1[0]-a[0], c1[1]-a[1]) + math.hypot(c2[0]-c1[0], c2[1]-c1[1]) + math.hypot(p[0]-c2[0], p[1]-c2[1])
        n = max(2, int(L / self.step))
        for i in range(1, n+1):
            t = i/n; u = 1-t
            self.cur.append((u**3*a[0]+3*u*u*t*c1[0]+3*u*t*t*c2[0]+t**3*p[0], u**3*a[1]+3*u*u*t*c1[1]+3*u*t*t*c2[1]+t**3*p[1]))
    def _qCurveToOne(self, c, p):
        a = self.cur[-1]
        L = math.hypot(c[0]-a[0], c[1]-a[1]) + math.hypot(p[0]-c[0], p[1]-c[1])
        n = max(2, int(L / self.step))
        for i in range(1, n+1):
            t = i/n; u = 1-t
            self.cur.append((u*u*a[0]+2*u*t*c[0]+t*t*p[0], u*u*a[1]+2*u*t*c[1]+t*t*p[1]))
    def _closePath(self): pass
    def _endPath(self): pass

def resample(pts, h):
    pts = np.array(pts, dtype=float)
    if np.allclose(pts[0], pts[-1]): pts = pts[:-1]
    closed = np.vstack([pts, pts[:1]])
    seg = np.hypot(*(np.diff(closed, axis=0).T))
    s = np.concatenate([[0], np.cumsum(seg)]); L = s[-1]
    n = max(8, int(round(L / h)))
    t = np.linspace(0, L, n, endpoint=False)
    x = np.interp(t, s, closed[:, 0]); y = np.interp(t, s, closed[:, 1])
    return np.stack([x, y], axis=1), L

def gsmooth(arr, sigma_pts):
    if sigma_pts <= 0: return arr
    r = int(3*sigma_pts) + 1
    k = np.exp(-0.5*(np.arange(-r, r+1)/sigma_pts)**2); k /= k.sum()
    n = len(arr)
    if n < 2*r+1:
        return arr
    out = np.empty_like(arr)
    for j in range(2):
        a = np.concatenate([arr[-r:, j], arr[:, j], arr[:r, j]])
        out[:, j] = np.convolve(a, k, mode='valid')
    return out

def catmull_d(pts):
    """closed Catmull-Rom through pts -> cubic path d"""
    n = len(pts); f = r2
    d = f'M{f(pts[0][0])} {f(pts[0][1])}'
    for i in range(n):
        p0 = pts[(i-1) % n]; p1 = pts[i]; p2 = pts[(i+1) % n]; p3 = pts[(i+2) % n]
        c1 = p1 + (p2 - p0)/6; c2 = p2 - (p3 - p1)/6
        d += f'C{f(c1[0])} {f(c1[1])} {f(c2[0])} {f(c2[1])} {f(p2[0])} {f(p2[1])}'
    return d + 'Z'

def smooth_d(d, sigma=2.0, knot=4.0, step=0.4, minlen=0, warp=None):
    """smooth every contour of d: resample, gaussian blur (sigma in units), refit through knots"""
    fp = FlatPen(step); parse_path(d, fp)
    out = []
    for c in fp.contours:
        if len(c) < 3: continue
        arr, L = resample(c, step)
        if L < minlen: continue
        if warp is not None: arr = warp(arr)
        sm = gsmooth(arr, sigma/step)
        kn, _ = resample(sm, knot)
        out.append(catmull_d(kn))
    return ''.join(out)

def bez_pts(ctrl, n=200):
    """sample a polyline of cubic bezier segments: ctrl = [p0, c1, c2, p1, c1, c2, p2...]"""
    pts = []
    for i in range(0, len(ctrl)-1, 3):
        p0, c1, c2, p1 = [np.array(c, float) for c in ctrl[i:i+4]]
        for t in np.linspace(0, 1, n, endpoint=(i+4 >= len(ctrl))):
            u = 1-t
            pts.append(u**3*p0 + 3*u*u*t*c1 + 3*u*t*t*c2 + t**3*p1)
    return np.array(pts)

def brush(center, w0, w1=None, wfun=None, caps=True, knot=3.0, sigma=0.8):
    """variable-width stroke outline along sampled centre polyline; widths from w0->w1 or wfun(t)"""
    c, L = None, None
    pts = np.array(center, float)
    seg = np.hypot(*np.diff(pts, axis=0).T); s = np.concatenate([[0], np.cumsum(seg)]); L = s[-1]
    n = max(20, int(L/1.0)); t = np.linspace(0, L, n)
    x = np.interp(t, s, pts[:, 0]); y = np.interp(t, s, pts[:, 1]); P = np.stack([x, y], 1)
    tt = t / L
    if wfun is None:
        w1 = w0 if w1 is None else w1
        W = w0 + (w1 - w0) * tt
    else:
        W = np.array([wfun(v) for v in tt])
    tg = np.gradient(P, axis=0); tg /= np.linalg.norm(tg, axis=1)[:, None]
    nm = np.stack([-tg[:, 1], tg[:, 0]], 1)
    left = P + nm * (W/2)[:, None]; right = P - nm * (W/2)[:, None]
    def cap(pc, r, d, k=16):
        # semicircle from left side to right side around end with direction d
        a0 = math.atan2(nm_[1], nm_[0])
    out = list(left)
    # end cap
    e = P[-1]; r = W[-1]/2; d = tg[-1]; a0 = math.atan2(nm[-1][1], nm[-1][0])
    for k in range(1, 16):
        a = a0 - math.pi * k/16
        out.append(e + r*np.array([math.cos(a), math.sin(a)]))
    out += list(right[::-1])
    b = P[0]; r = W[0]/2; a0 = math.atan2(-nm[0][1], -nm[0][0])
    for k in range(1, 16):
        a = a0 - math.pi * k/16
        out.append(b + r*np.array([math.cos(a), math.sin(a)]))
    arr = np.array(out)
    d = 'M' + 'L'.join(f'{p[0]:.2f} {p[1]:.2f}' for p in arr) + 'Z'
    p = pathops.simplify(P_from_d(d))
    return p


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1); return t*t*(3-2*t)

def lower_top(y_from, y_to, shift):
    """warp: points above y_from (more negative) move down by shift (smoothly ramping between y_from and y_to)"""
    def f(arr):
        a = arr.copy()
        k = smoothstep(-y_from, -y_to, -a[:, 1])
        a[:, 1] = a[:, 1] + shift * k
        return a
    return f
