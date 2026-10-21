"""Paw geometry for 06: chubby puppy paw = ink pad (home) + four toes (breeds)."""
import math
from lib import *


def pad(cx, cy, w, h, top_r=None):
    """Chubby rounded-triangle pad, slightly lobed bottom. (cx,cy)=centre of bbox."""
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - h / 2, cy + h / 2
    pts = [(cx, y0 - h * 0.05), (x1 + w * 0.02, y1 - h * 0.08), (cx, y1 + h * 0.06), (x0 - w * 0.02, y1 - h * 0.08)]
    r = [w * 0.30, w * 0.24, w * 0.55, w * 0.24]
    p = rounded_poly(pts, r)
    # trim to bbox to normalise
    return p


def pad2(cx, cy, w, h):
    """pad built from a superellipse body + top dome: chubby bean."""
    body = superellipse(cx, cy + h * 0.12, w / 2, h * 0.38, 2.6)
    dome = ellipse(cx, cy - h * 0.12, w * 0.33, h * 0.38)
    return fillet(union(body, dome), w * 0.12)


def toe(cx, cy, r, squash=1.12, rot=0):
    return ellipse(cx, cy, r, r * squash, rot)


def layout(pcx, pcy, pw, ph, tr, gap, spread_deg=(-62, -22, 22, 62), squash=1.12, radial=1.0):
    """Toe centres on an arc around pad top: returns list of (x,y,rot). Arc centre below pad centre."""
    acx, acy = pcx, pcy + ph * 0.10
    R = ph * 0.5 + gap + tr * squash + ph * 0.02
    out = []
    for a in spread_deg:
        t = math.radians(a)
        x = acx + R * math.sin(t) * radial
        y = acy - R * math.cos(t)
        out.append((x, y, a))
    return out


def area(p):
    try:
        return abs(p.area)
    except Exception:
        return 0.0


def touches(a, b, gap):
    """True if a and b are closer than gap."""
    return area(inter(dilate(a, gap / 2), dilate(b, gap / 2))) > 1e-3


def place_toe(P, ox, oy, ang, r, squash, gap, tilt=1.0):
    """slide a toe along ray from (ox,oy) at angle ang (0 = up) until it sits exactly gap away from P."""
    t = math.radians(ang)
    dx, dy = math.sin(t), -math.cos(t)
    lo, hi = 0.0, 400.0
    for _ in range(26):
        mid = (lo + hi) / 2
        T = ellipse(ox + dx * mid, oy + dy * mid, r, r * squash, ang * tilt)
        if touches(T, P, gap):
            lo = mid
        else:
            hi = mid
    return ellipse(ox + dx * hi, oy + dy * hi, r, r * squash, ang * tilt), (ox + dx * hi, oy + dy * hi)


def pad3(cx, cy, w, h, notch=0.0, top=0.36, corner=0.2, belly=0.0, belly_r=0.9):
    """rounded triangle pad with broad base; optional convex belly / soft notch at bottom centre."""
    if belly:
        p = rounded_poly([(cx, cy - h * 0.75), (cx + w * 0.62, cy + h * 0.5), (cx, cy + h * (0.5 + belly)), (cx - w * 0.62, cy + h * 0.5)],
                         [w * top, w * corner, w * belly_r, w * corner])
    else:
        p = rounded_poly([(cx, cy - h * 0.75), (cx + w * 0.62, cy + h * 0.5), (cx - w * 0.62, cy + h * 0.5)], [w * top, w * corner, w * corner])
    if notch:
        p = diff(p, ellipse(cx, cy + h * 0.5 + notch * h * 0.25, w * 0.12, notch * h * 0.42))
        p = soften(p, w * 0.04)
    # normalise to bbox
    b = p.bounds
    sx = w / (b[2] - b[0]); sy = h / (b[3] - b[1])
    p = p.transform(sx, 0, 0, sy, cx - sx * (b[0] + b[2]) / 2, cy - sy * (b[1] + b[3]) / 2)
    return p


def pad4(cx, cy, w, h, n=3.2):
    """squircle pad (the site tile)."""
    return superellipse(cx, cy, w / 2, h / 2, n)


def pad5(cx, cy, w, h):
    """bean: superellipse body with softly raised top centre (lobes at bottom)."""
    top = ellipse(cx, cy - h * 0.08, w * 0.36, h * 0.42)
    body = superellipse(cx, cy + h * 0.14, w * 0.5, h * 0.36, 2.2)
    p = fillet(union(top, body), w * 0.16)
    b = p.bounds
    sx = w / (b[2] - b[0]); sy = h / (b[3] - b[1])
    return p.transform(sx, 0, 0, sy, cx - sx * (b[0] + b[2]) / 2, cy - sy * (b[1] + b[3]) / 2)


def soft_tri(cx, cy, w, h, bulge=0.28, corner=0.5, steps=180):
    """convex soft triangle (apex up): mix of rounded triangle and ellipse radial distance, then normalised to w x h."""
    base = rounded_poly([(0, -1.0), (1.0, 0.72), (-1.0, 0.72)], [0.62, corner * 0.62, corner * 0.62])
    # sample base outline radially from centroid
    import pathops as po
    cyc = 0.15
    pts = []
    # use polygon sampling via flattening
    flat = []
    for verb, ps in base:
        if verb == po.PathVerb.MOVE:
            cur = ps[0]; flat.append(cur)
        elif verb == po.PathVerb.LINE:
            for i in range(1, 9):
                t = i / 8
                flat.append((cur[0] + (ps[0][0] - cur[0]) * t, cur[1] + (ps[0][1] - cur[1]) * t))
            cur = ps[0]
        elif verb == po.PathVerb.CUBIC:
            p0 = cur; p1, p2, p3 = ps
            for i in range(1, 13):
                t = i / 12; u = 1 - t
                flat.append((u**3*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t**3*p3[0], u**3*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t**3*p3[1]))
            cur = p3
    out = []
    for (x, y) in flat:
        dx, dy = x, y - cyc
        r = math.hypot(dx, dy)
        a = math.atan2(dy, dx)
        # ellipse radius at same angle (ellipse 1.0 x 0.86 centred at cyc)
        ex, ey = 1.0, 0.86
        re = 1 / math.sqrt((math.cos(a) / ex) ** 2 + (math.sin(a) / ey) ** 2)
        rr = r * (1 - bulge) + re * bulge
        out.append((math.cos(a) * rr, cyc + math.sin(a) * rr))
    # thin points
    out = out[::2]
    p = smooth_closed(out)
    b = p.bounds
    sx = w / (b[2] - b[0]); sy = h / (b[3] - b[1])
    return p.transform(sx, 0, 0, sy, cx - sx * (b[0] + b[2]) / 2, cy - sy * (b[1] + b[3]) / 2)
