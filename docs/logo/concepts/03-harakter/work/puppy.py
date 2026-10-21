"""The puppy built from the «о» glyph (round 3).

Head  = the «о» ring, same colour as the word (ink / cream).
Ears  = long hanging flaps grown out of the top of the head, separated from the cheeks below
        by a slit with round ends. Lobes hang a little below the baseline -> a spaniel, not a bear.
Face  = the counter redrawn as a blaze: a narrow nose bridge between the eyes that widens into the muzzle.
        Face + eyes are the only coral of the logo (or knocked out in mono / in the mark).
Nose  = a soft inverted triangle at the top of the muzzle, always ink.

All sizes are fractions of the «о» outer half-width r. Every custom outline is refitted by fit.clean():
cubic Beziers, true corners only where intended, no stair-steps.
"""
from geo import *
from fit import clean, offset

DEF = dict(
    bridge_w=0.30, bridge_top=-0.60,                 # nose bridge: width, top (y from centre)
    muzzle_w=0.98, muzzle_top=-0.12, muzzle_bot=0.66,  # muzzle: width, top, bottom
    blaze_fillet=0.16,                               # concave fillet bridge -> muzzle
    nose_w=0.50, nose_h=0.34, nose_y=0.12, nose_round=0.11,
    eye_x=0.42, eye_y=-0.30, eye_r=0.115,
    ear_pts=[(0.3, -0.72), (0.74, -0.8), (1.06, -0.56), (1.24, 0.0), (1.33, 0.66),
             (1.16, 1.1), (0.93, 1.06), (0.86, 0.6), (0.62, -0.2)],
    slit_from=-0.45,      # the slit between ear and cheek starts here (y from centre); above it the ear grows from the head
    ear_gap=0.12,         # slit width
    ear_fillet=0.07,      # convex corners where the slit meets the ear
    valley=0.14,          # concave fillet where the ear leaves the top of the head
    ear_release=0.22,     # concave fillet where the ear's inner edge leaves the slit and hangs free
)


def o_parts(o):
    cs = contours(o)
    outer = max(cs, key=lambda c: abs(c.area))
    x0, y0, x1, y1 = outer.bounds
    return outer, ((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2)


def spline(pts, k=1 / 6):
    """closed Catmull-Rom spline through pts -> cubic Bezier Path"""
    p = Path()
    pen = p.getPen()
    n = len(pts)
    pen.moveTo(pts[0])
    for i in range(n):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * k, p1[1] + (p2[1] - p0[1]) * k)
        c2 = (p2[0] - (p3[0] - p1[0]) * k, p2[1] - (p3[1] - p1[1]) * k)
        pen.curveTo(c1, c2, p2)
    pen.closePath()
    return simplify(p)


def blaze(cx, cy, r, P):
    bw, mw = P['bridge_w'] * r, P['muzzle_w'] * r
    top, mt, mb = cy + P['bridge_top'] * r, cy + P['muzzle_top'] * r, cy + P['muzzle_bot'] * r
    bridge = rrect(cx - bw / 2, top, cx + bw / 2, mt + 0.2 * r, bw / 2)
    mh = mb - mt
    muzzle = ellipse(cx, mt + mh * 0.5, mw / 2, mh * 0.53)
    muzzle = inter(muzzle, rect(cx - mw, mt - r, cx + mw, mb))
    return clean(union(bridge, muzzle), tol=0.001 * r, fillet=P['blaze_fillet'] * r, window=0.03 * r, thresh=25)


def rounded_polygon(pts, radii):
    """polygon with each corner replaced by an exact circular arc (cubic approximation) of its own radius"""
    import math
    n = len(pts)
    segs = []
    for i in range(n):
        V, A, B = pts[i], pts[i - 1], pts[(i + 1) % n]
        u1 = ((A[0] - V[0]), (A[1] - V[1]))
        u2 = ((B[0] - V[0]), (B[1] - V[1]))
        l1, l2 = math.hypot(*u1), math.hypot(*u2)
        u1, u2 = (u1[0] / l1, u1[1] / l1), (u2[0] / l2, u2[1] / l2)
        ang = math.acos(max(-1, min(1, u1[0] * u2[0] + u1[1] * u2[1])))
        rho = radii[i]
        t = rho / math.tan(ang / 2)
        T1 = (V[0] + u1[0] * t, V[1] + u1[1] * t)
        T2 = (V[0] + u2[0] * t, V[1] + u2[1] * t)
        k = 4 / 3 * math.tan((math.pi - ang) / 4) * rho
        segs.append((T1, (T1[0] - u1[0] * k, T1[1] - u1[1] * k), (T2[0] - u2[0] * k, T2[1] - u2[1] * k), T2))
    p = Path()
    pen = p.getPen()
    pen.moveTo(segs[0][0])
    for i, (T1, c1, c2, T2) in enumerate(segs):
        if i:
            pen.lineTo(T1)
        pen.curveTo(c1, c2, T2)
    pen.closePath()
    return p


def nose(cx, cy, r, P):
    w, h = P['nose_w'] * r, P['nose_h'] * r
    y = cy + P['nose_y'] * r
    pts = [(cx - w / 2, y - h * 0.45), (cx + w / 2, y - h * 0.45), (cx, y + h * 0.55)]
    rr = P['nose_round'] * r
    return rounded_polygon(pts, [rr, rr, rr * 0.8])


def ear(cx, cy, r, s, P):
    return spline([(cx + s * x * r, cy + y * r) for x, y in P['ear_pts']])


def slit(head, gap, y_from):
    """the gap between ears and cheeks: a band of width `gap` that follows the head outline below `y_from`,
    drawn as a round-capped stroke along the outline offset by gap/2 (so both ends are clean semicircles)"""
    import numpy as np
    from fit import _flatten_contours, _resample_closed
    mid = offset(head, gap / 2)
    P_, ds = _resample_closed(_flatten_contours(mid, 0.2)[0][1], 0.4)
    below = P_[:, 1] > y_from
    # rotate so the run below y_from is contiguous
    start = int(np.argmax(~below & np.roll(below, -1))) + 1
    Q = np.roll(P_, -start, axis=0)
    Q = Q[Q[:, 1] > y_from]
    line = polyline([tuple(q) for q in Q])
    return clean(stroke(line, gap, cap='round', join='round'), tol=0.0006 * gap * 8, window=gap * 0.15, thresh=40)


def puppy(o, P=None):
    """o = «о» glyph path -> dict(body = head + ears with face/eyes open, face = blaze + eyes, nose, solid)"""
    P = dict(DEF, **(P or {}))
    outer, (cx, cy, r) = o_parts(o)
    head = simplify(outer)
    gap = P['ear_gap'] * r
    band = slit(head, gap, cy + P['slit_from'] * r)
    ears = union(*[diff(ear(cx, cy, r, s, P), head, band) for s in (-1, 1)])
    # drop hairline leftovers of the boolean (pieces thinner than the slit)
    ears = union(*[c for c in contours(ears) if abs(c.area) > 0.05 * r * r])
    y_slit = cy + P['slit_from'] * r

    def fil(pt, convex):
        """fillets by zone: the valley where an ear leaves the top of the head, the release where an ear's
        inner edge leaves the slit and hangs free, a small rounding on convex corners; slit ends stay round"""
        if pt[1] > cy + 0.2 * r:
            return P['ear_release'] * r
        if convex:
            return P['ear_fillet'] * r
        if pt[1] < y_slit - 0.05 * r:
            return P['valley'] * r
        return 0.0
    sil = clean(union(head, ears), tol=0.001 * r, fillet=fil, window=0.035 * r, thresh=28)
    bl = blaze(cx, cy, r, P)
    eyes = union(*[circle(cx + s * P['eye_x'] * r, cy + P['eye_y'] * r, P['eye_r'] * r) for s in (-1, 1)])
    ns = nose(cx, cy, r, P)
    face = union(bl, eyes)
    body = diff(sil, face)
    return dict(body=body, face=face, nose=ns, solid=union(body, ns), full=sil,
                center=(cx, cy, r))
