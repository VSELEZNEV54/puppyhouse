"""Paw v2 for 06: compact puppy paw. One gap rule: toe-to-pad gap and toe-to-toe gap are solved numerically,
so the four toes sit as a snug arc (a puppy's chubby toes), not as scattered confetti dots."""
import math
import numpy as np
from lib import *          # noqa
from paw import pad3       # noqa


def pts_of(p, n=240):
    return np.array(resample(flatten(p), n))


def mind(a, b):
    """minimum distance between two closed outlines (sampled)."""
    A = pts_of(a) if not isinstance(a, np.ndarray) else a
    B = pts_of(b) if not isinstance(b, np.ndarray) else b
    d = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
    return float(d.min())


def toe_shape(cx, cy, r, sq, ang, egg=0.0):
    """toe: ellipse r x r*sq rotated radially (ang, 0 = up). egg > 0 narrows the end that faces the pad."""
    if not egg:
        return ellipse(cx, cy, r, r * sq, ang)
    # egg: sample an ellipse and pinch the lower half (towards the pad) in x
    pts = []
    for i in range(96):
        t = 2 * math.pi * i / 96
        x, y = r * math.cos(t), r * sq * math.sin(t)
        if y > 0:   # lower half (pad side, y down)
            x *= 1 - egg * (y / (r * sq)) ** 1.6
        pts.append((x, y))
    p = smooth_closed(resample(pts, 48))
    p = rotate(p, ang, 0, 0)
    return move(p, cx, cy)


def slide(pad_pts, ox, oy, ang, r, sq, gap, egg=0.0):
    t = math.radians(ang)
    dx, dy = math.sin(t), -math.cos(t)
    lo, hi = 0.0, 300.0
    for _ in range(30):
        mid = (lo + hi) / 2
        T = toe_shape(ox + dx * mid, oy + dy * mid, r, sq, ang, egg)
        # inside or too close -> push out
        inside = pad_inside(pad_pts, ox + dx * mid, oy + dy * mid)
        if inside or mind(pts_of(T), pad_pts) < gap:
            lo = mid
        else:
            hi = mid
    return toe_shape(ox + dx * hi, oy + dy * hi, r, sq, ang, egg)


def pad_inside(P, x, y):
    # ray casting on sampled pad
    n = len(P); c = False
    for i in range(n):
        x1, y1 = P[i]; x2, y2 = P[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            c = not c
    return c


def pad_taper(w, h, k=0.25, n_top=2.3, n_bot=2.9, steps=720, out_n=140):
    """main pad as a tapered superellipse: x is scaled by (1 + k*y), a smooth linear taper, so the outline is
    one analytic curve with no straight bits and no curvature jumps ("shoulders"). k narrows the top and widens
    the base; n_top rounds the dome, n_bot squares the base a little."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        c, s_ = math.cos(t), math.sin(t)
        n = n_bot if s_ > 0 else n_top                 # y down: s_ > 0 is the lower half
        y = math.copysign(abs(s_) ** (2 / n), s_)      # -1 (top) .. 1 (base)
        x = math.copysign(abs(c) ** (2 / n), c) * (1 + k * y)
        pts.append((x * w / 2, y * h / 2))
    p = smooth_closed(resample(pts, out_n))
    b = p.bounds
    sx = w / (b[2] - b[0]); sy = h / (b[3] - b[1])
    return p.transform(sx, 0, 0, sy, -sx * (b[0] + b[2]) / 2, -sy * (b[1] + b[3]) / 2)


def build_paw(pw=60, ph=46, top=0.40, corner=0.26, smooth=9.0, r=11.0, sq=1.12, k_out=0.9,
              gap=3.6, gap_tt=None, ody=6.0, egg=0.0, out_drop=0.0, belly=0.0, belly_r=1.1, notch=0.0,
              pad_kind='tri', k=0.25, n_top=2.3, n_bot=2.9, out_n=72):
    """returns pad, [4 toes] (left->right), unit-normalised later by caller."""
    gap_tt = gap if gap_tt is None else gap_tt
    if pad_kind == 'taper':
        pad = pad_taper(pw, ph, k, n_top, n_bot)
        smooth = 0
    else:
        pad = pad3(0, 0, pw, ph, notch=notch, top=top, corner=corner, belly=belly, belly_r=belly_r)
    if smooth:
        pad = smooth_outline(pad, sigma=smooth, out_n=out_n)
        b = pad.bounds
        sx = pw / (b[2] - b[0]); sy = ph / (b[3] - b[1])
        pad = pad.transform(sx, 0, 0, sy, -sx * (b[0] + b[2]) / 2, -sy * (b[1] + b[3]) / 2)
    P = pts_of(pad, 360)
    # inner toes: find a1 so the two inner toes are gap_tt apart
    def inner(a):
        return slide(P, 0, ody, a, r, sq, gap, egg)
    lo, hi = 2.0, 60.0
    for _ in range(18):
        a = (lo + hi) / 2
        T = inner(a)
        Tm = T.transform(-1, 0, 0, 1, 0, 0)
        if mind(T, Tm) < gap_tt:
            lo = a
        else:
            hi = a
    a1 = hi
    Ti = inner(a1)
    ro = r * k_out
    # outer toe: find a2 > a1 so outer-to-inner gap == gap_tt
    def outer(a):
        return slide(P, 0, ody + out_drop, a, ro, sq, gap, egg)
    lo, hi = a1 + 5, a1 + 80
    for _ in range(18):
        a = (lo + hi) / 2
        T = outer(a)
        if mind(T, Ti) < gap_tt:
            lo = a
        else:
            hi = a
    a2 = hi
    To = outer(a2)
    mirror = lambda p: p.transform(-1, 0, 0, 1, 0, 0)
    toes = [mirror(To), mirror(Ti), Ti, To]
    return pad, toes, (a1, a2)
