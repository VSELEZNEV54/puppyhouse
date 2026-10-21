"""Clean-outline kit: turns any pathops Path (booleans, strokes, offsets) into a few smooth cubic Beziers.

  clean(path, tol, fillet)  resample every contour by arc length, find true corners, optionally round them
                            with a fillet of radius `fillet`, then fit cubics (Schneider) within `tol`.
                            Straight runs come out as single L segments. No stair-steps, no micro-segments.
  offset(path, d)           outward (d > 0) / inward (d < 0) offset of a smooth closed shape, refitted clean.
"""
import math
import numpy as np
from pathops import Path


# ---------- flatten ----------
def _flatten_contours(p, step=0.35):
    """list of (closed, np.array points) with segment junction indices"""
    out = []
    cur, start, juncs = [], None, []

    def add_curve(pts):
        n = max(4, int(_poly_len(pts) / step) + 1)
        return pts, n

    last = None
    for verb, pts in p.segments:
        if verb == 'moveTo':
            cur = [np.array(pts[0], float)]
            juncs = [0]
            last = np.array(pts[0], float)
        elif verb == 'lineTo':
            for q in pts:
                q = np.array(q, float)
                L = np.linalg.norm(q - last)
                n = max(1, int(L / step))
                for i in range(1, n + 1):
                    cur.append(last + (q - last) * i / n)
                juncs.append(len(cur) - 1)
                last = q
        elif verb == 'curveTo':
            c1, c2, q = [np.array(v, float) for v in pts]
            L = np.linalg.norm(c1 - last) + np.linalg.norm(c2 - c1) + np.linalg.norm(q - c2)
            n = max(4, int(L / step))
            for i in range(1, n + 1):
                t = i / n
                mt = 1 - t
                cur.append(mt ** 3 * last + 3 * mt * mt * t * c1 + 3 * mt * t * t * c2 + t ** 3 * q)
            juncs.append(len(cur) - 1)
            last = q
        elif verb == 'qCurveTo':
            # TrueType-style implied on-curve points
            ctrl = [np.array(v, float) for v in pts[:-1]]
            end = np.array(pts[-1], float)
            ons = []
            for i, c in enumerate(ctrl):
                nxt = (ctrl[i + 1] + c) / 2 if i + 1 < len(ctrl) else end
                ons.append((c, nxt))
            for c, q in ons:
                L = np.linalg.norm(c - last) + np.linalg.norm(q - c)
                n = max(4, int(L / step))
                for i in range(1, n + 1):
                    t = i / n
                    mt = 1 - t
                    cur.append(mt * mt * last + 2 * mt * t * c + t * t * q)
                juncs.append(len(cur) - 1)
                last = q
        elif verb in ('closePath', 'endPath'):
            arr = np.array(cur)
            if verb == 'closePath' and np.linalg.norm(arr[-1] - arr[0]) < 1e-6:
                arr = arr[:-1]
            out.append((verb == 'closePath', arr))
    return out


def _poly_len(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _resample_closed(pts, step):
    P = np.vstack([pts, pts[:1]])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    n = max(12, int(round(total / step)))
    t = np.linspace(0, total, n, endpoint=False)
    x = np.interp(t, s, P[:, 0])
    y = np.interp(t, s, P[:, 1])
    return np.stack([x, y], 1), total / n


# ---------- corners ----------
def _turn(P, k):
    n = len(P)
    a = P[(np.arange(n) - k) % n]
    b = P[(np.arange(n) + k) % n]
    d1 = P - a
    d2 = b - P
    ang1 = np.arctan2(d1[:, 1], d1[:, 0])
    ang2 = np.arctan2(d2[:, 1], d2[:, 0])
    d = (ang2 - ang1 + np.pi) % (2 * np.pi) - np.pi
    return np.degrees(np.abs(d))


def _corners(P, ds, window, thresh):
    k = max(1, int(round(window / ds)))
    t = _turn(P, k)
    n = len(P)
    idx = []
    for i in range(n):
        if t[i] < thresh:
            continue
        lo, hi = i - k, i + k
        if all(t[i] >= t[j % n] for j in range(lo, hi + 1)):
            if not idx or (i - idx[-1]) > k:
                idx.append(i)
    if len(idx) > 1 and (idx[0] + n - idx[-1]) <= k:
        idx.pop()
    return idx


def _fillet(P, ds, corners, r, sign=1):
    """replace the points within r of each corner by a quadratic blend through the corner tangents.
    r = radius, or (convex_r, concave_r); sign = orientation of the fill (+1/-1)"""
    if not corners:
        return P, corners
    n = len(P)
    keep = np.ones(n, bool)
    new_pts = {}
    cs_sorted = sorted(corners)
    for ci, c in enumerate(cs_sorted):
        d1 = P[c] - P[(c - 2) % n]
        d2 = P[(c + 2) % n] - P[c]
        convex = (d1[0] * d2[1] - d1[1] * d2[0]) * sign > 0
        if callable(r):
            rr = r(tuple(P[c]), convex)
        elif isinstance(r, (tuple, list)):
            rr = r[0] if convex else r[1]
        else:
            rr = r
        if rr <= 0:
            continue
        m = max(2, int(round(rr / ds)))
        if len(cs_sorted) > 1:
            prv = cs_sorted[ci - 1]
            nxt = cs_sorted[(ci + 1) % len(cs_sorted)]
            room = min((c - prv) % n, (nxt - c) % n)
            m = max(1, min(m, room // 2 - 1))
        a = P[(c - m) % n]
        b = P[(c + m) % n]
        q = P[c]
        seg = []
        for j in range(1, 2 * m):
            t = j / (2 * m)
            seg.append((1 - t) ** 2 * a + 2 * (1 - t) * t * q + t * t * b)
        for j in range(c - m + 1, c + m):
            keep[j % n] = False
        new_pts[c] = seg
    out = []
    for i in range(n):
        if keep[i]:
            out.append(P[i])
        if i in new_pts:
            out.extend(new_pts[i])
    return np.array(out), []


def _area(P):
    return 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])


# ---------- Schneider cubic fitting ----------
def _bez(b, t):
    t = t[:, None]
    mt = 1 - t
    return mt ** 3 * b[0] + 3 * mt * mt * t * b[1] + 3 * mt * t * t * b[2] + t ** 3 * b[3]


def _bez1(b, t):
    t = t[:, None]
    mt = 1 - t
    return 3 * mt * mt * (b[1] - b[0]) + 6 * mt * t * (b[2] - b[1]) + 3 * t * t * (b[3] - b[2])


def _bez2(b, t):
    t = t[:, None]
    return 6 * (1 - t) * (b[2] - 2 * b[1] + b[0]) + 6 * t * (b[3] - 2 * b[2] + b[1])


def _chord(P):
    d = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return d / d[-1] if d[-1] > 0 else d


def _generate(P, u, t1, t2):
    p0, p3 = P[0], P[-1]
    B0 = (1 - u) ** 3
    B1 = 3 * u * (1 - u) ** 2
    B2 = 3 * u * u * (1 - u)
    B3 = u ** 3
    A1 = t1[None, :] * B1[:, None]
    A2 = t2[None, :] * B2[:, None]
    C00 = np.sum(A1 * A1)
    C01 = np.sum(A1 * A2)
    C11 = np.sum(A2 * A2)
    tmp = P - (p0[None] * (B0 + B1)[:, None] + p3[None] * (B2 + B3)[:, None])
    X0 = np.sum(A1 * tmp)
    X1 = np.sum(A2 * tmp)
    det = C00 * C11 - C01 * C01
    seg = np.linalg.norm(p3 - p0)
    if abs(det) > 1e-12:
        a1 = (X0 * C11 - X1 * C01) / det
        a2 = (C00 * X1 - C01 * X0) / det
    else:
        a1 = a2 = seg / 3
    eps = 1e-6 * seg
    if a1 < eps or a2 < eps:
        a1 = a2 = seg / 3
    return np.array([p0, p0 + t1 * a1, p3 + t2 * a2, p3])


def _reparam(P, u, b):
    q = _bez(b, u) - P
    q1 = _bez1(b, u)
    q2 = _bez2(b, u)
    num = np.sum(q * q1, 1)
    den = np.sum(q1 * q1, 1) + np.sum(q * q2, 1)
    ok = np.abs(den) > 1e-12
    nu = u.copy()
    nu[ok] = u[ok] - num[ok] / den[ok]
    nu = np.clip(nu, 0, 1)
    nu[0], nu[-1] = 0, 1
    if np.any(np.diff(nu) < 0):
        return u
    return nu


def _max_err(P, b, u):
    d = np.sum((_bez(b, u) - P) ** 2, 1)
    i = int(np.argmax(d))
    return math.sqrt(d[i]), i


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _fit(P, t1, t2, err, depth=0):
    if len(P) == 2:
        d = np.linalg.norm(P[1] - P[0]) / 3
        return [np.array([P[0], P[0] + t1 * d, P[1] + t2 * d, P[1]])]
    u = _chord(P)
    b = _generate(P, u, t1, t2)
    e, split = _max_err(P, b, u)
    if e < err:
        return [b]
    if e < err * 6:
        for _ in range(12):
            u = _reparam(P, u, b)
            b = _generate(P, u, t1, t2)
            e, split = _max_err(P, b, u)
            if e < err:
                return [b]
    split = min(max(split, 2), len(P) - 3) if len(P) > 4 else len(P) // 2
    tc = _unit(P[split - 1] - P[split + 1])
    return _fit(P[:split + 1], t1, tc, err, depth + 1) + _fit(P[split:], -tc, t2, err, depth + 1)


def _tan(P, i, k, closed=True):
    n = len(P)
    a = P[(i - k) % n]
    b = P[(i + k) % n]
    return _unit(b - a)


def _is_line(P, tol):
    a, b = P[0], P[-1]
    d = b - a
    L = np.linalg.norm(d)
    if L < 1e-9:
        return False
    nrm = np.array([-d[1], d[0]]) / L
    return np.max(np.abs((P - a) @ nrm)) < tol


# ---------- public ----------
def clean(p, tol=0.08, fillet=0.0, window=1.2, thresh=38, step=None, line_tol=None):
    """resample + corner-aware refit of every closed contour of a pathops Path"""
    out = Path()
    pen = out.getPen()
    st = step or 0.3
    lt = line_tol if line_tol is not None else tol * 0.6
    conts = [c for c in _flatten_contours(p, st / 2) if len(c[1]) >= 3]
    gsign = 1
    if conts:
        big = max(conts, key=lambda c: abs(_area(c[1])))
        gsign = 1 if _area(big[1]) > 0 else -1
    has_fillet = callable(fillet) or (max(fillet) if isinstance(fillet, (tuple, list)) else fillet) > 0
    for closed, raw in conts:
        P, ds = _resample_closed(raw, st)
        cs = _corners(P, ds, window, thresh)
        if has_fillet and cs:
            P, _ = _fillet(P, ds, cs, fillet, gsign)
            P, ds = _resample_closed(P, st)
            cs = _corners(P, ds, window * 0.3, thresh)   # fillets are smooth now; only unfilleted corners remain
        n = len(P)
        k = max(1, int(round(0.8 / ds)))
        if not cs:
            # smooth closed contour: start at the top-most point, fit as one loop
            s = int(np.argmin(P[:, 1]))
            Q = np.vstack([P[s:], P[:s], P[s:s + 1]])
            t = _tan(P, s, k)
            beziers = _fit(Q, t, -t, tol)
            runs = [('c', beziers)]
            start = Q[0]
        else:
            runs = []
            start = P[cs[0]]
            for j, c in enumerate(cs):
                c2 = cs[(j + 1) % len(cs)]
                idx = np.arange(c, c2 + (n if c2 <= c else 0) + 1) % n
                R = P[idx]
                if _is_line(R, lt):
                    runs.append(('l', R[-1]))
                    continue
                # one-sided tangents at corners
                kk = min(k, max(1, len(R) // 3))
                t1 = _unit(R[kk] - R[0])
                t2 = _unit(R[-1 - kk] - R[-1])
                runs.append(('c', _fit(R, t1, t2, tol)))
        pen.moveTo(tuple(start))
        for kind, v in runs:
            if kind == 'l':
                pen.lineTo(tuple(v))
            else:
                for b in v:
                    pen.curveTo(tuple(b[1]), tuple(b[2]), tuple(b[3]))
        pen.closePath()
    return out


def drift(a, b):
    """area of the symmetric difference between two shapes, relative to the area of a"""
    from pathops import op, PathOp
    x = op(a, b, PathOp.XOR, fix_winding=True)
    return abs(x.area) / max(abs(a.area), 1e-9)


def offset(p, d, tol=0.06, step=0.3):
    """offset of smooth closed contours along the normal (outer contours grow for d > 0); refit clean"""
    out = Path()
    pen = out.getPen()
    for closed, raw in _flatten_contours(p, step / 2):
        P, ds = _resample_closed(raw, step)
        n = len(P)
        k = 2
        T = np.array([_tan(P, i, k) for i in range(n)])
        # orientation: positive area in y-down coords -> clockwise visually
        area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        N = np.stack([T[:, 1], -T[:, 0]], 1)  # right-hand normal
        sgn = 1 if area < 0 else -1
        Q = P + N * d * sgn
        # make sure we grew: compare enclosed area magnitude
        a2 = 0.5 * np.sum(Q[:, 0] * np.roll(Q[:, 1], -1) - np.roll(Q[:, 0], -1) * Q[:, 1])
        if (abs(a2) > abs(area)) != (d > 0):
            Q = P - N * d * sgn
        s = int(np.argmin(Q[:, 1]))
        R = np.vstack([Q[s:], Q[:s], Q[s:s + 1]])
        t = _tan(Q, s, 2)
        for i, b in enumerate(_fit(R, t, -t, tol)):
            if i == 0:
                pen.moveTo(tuple(b[0]))
            pen.curveTo(tuple(b[1]), tuple(b[2]), tuple(b[3]))
        pen.closePath()
    return out


def stats(p):
    """(segments, line segments, shortest segment length)"""
    nseg = nl = 0
    shortest = 1e9
    last = None
    for verb, pts in p.segments:
        if verb == 'moveTo':
            last = pts[0]
            continue
        if verb in ('closePath', 'endPath'):
            continue
        nseg += 1
        if verb == 'lineTo':
            nl += 1
        end = pts[-1]
        shortest = min(shortest, math.dist(last, end))
        last = end
    return nseg, nl, shortest
