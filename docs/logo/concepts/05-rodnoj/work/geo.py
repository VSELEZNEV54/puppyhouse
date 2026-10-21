"""Geometric helpers for the 05 mark: circular arcs as cubic Béziers, drop shapes (two circles + external tangents)."""
import math
from lib import P


def arc_cmds(cx, cy, r, a0, a1):
    """cubic segments for a circular arc from angle a0 to a1 (radians, SVG y-down), returns 'C...' string; assumes the pen is at the start"""
    out = ''
    n = max(1, int(math.ceil(abs(a1 - a0) / (math.pi / 2) - 1e-9)))
    da = (a1 - a0) / n
    k = 4 / 3 * math.tan(da / 4)
    for i in range(n):
        s, e = a0 + i * da, a0 + (i + 1) * da
        x0, y0 = cx + r * math.cos(s), cy + r * math.sin(s)
        x3, y3 = cx + r * math.cos(e), cy + r * math.sin(e)
        x1, y1 = x0 - k * r * math.sin(s), y0 + k * r * math.cos(s)
        x2, y2 = x3 + k * r * math.sin(e), y3 - k * r * math.cos(e)
        out += f"C{x1:.4f} {y1:.4f} {x2:.4f} {y2:.4f} {x3:.4f} {y3:.4f}"
    return out


def drop(c1, r1, c2, r2):
    """convex hull of two circles (c1 small/top, c2 big/bottom) -> closed path"""
    (x1, y1), (x2, y2) = c1, c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    base = math.atan2(dy, dx)
    # external tangent: angle offset from the centre line
    phi = math.acos((r1 - r2) / d)
    # tangent points: on each circle at angles base ± phi
    aL, aR = base + phi, base - phi
    p1a = (x1 + r1 * math.cos(aR), y1 + r1 * math.sin(aR))
    p2a = (x2 + r2 * math.cos(aR), y2 + r2 * math.sin(aR))
    p2b = (x2 + r2 * math.cos(aL), y2 + r2 * math.sin(aL))
    p1b = (x1 + r1 * math.cos(aL), y1 + r1 * math.sin(aL))
    d_ = f"M{p1a[0]:.4f} {p1a[1]:.4f}L{p2a[0]:.4f} {p2a[1]:.4f}"
    d_ += arc_cmds(x2, y2, r2, aR, aL if aL > aR else aL + 2 * math.pi)
    d_ += f"L{p1b[0]:.4f} {p1b[1]:.4f}"
    a_end = aR + 2 * math.pi
    d_ += arc_cmds(x1, y1, r1, aL, a_end if a_end > aL else a_end + 2 * math.pi)
    d_ += 'Z'
    return P(d_)


def arc_path(cx, cy, r, a0, a1):
    x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
    from lib import open_path
    return open_path(f"M{x0:.4f} {y0:.4f}" + arc_cmds(cx, cy, r, a0, a1))


def hull(circs):
    """convex hull of circles [((x, y), r), ...] given in hull order (any direction); every circle must touch the hull.
    Built analytically: outer tangent segments + circular arcs (cubic Béziers)."""
    import math as m
    if len(circs) == 2:
        (a, ra), (b, rb) = circs
        return drop(a, ra, b, rb)
    pts = [c for c, r in circs]
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
    if area < 0:
        circs = circs[::-1]
    n = len(circs)
    cx = sum(c[0] for c, r in circs) / n
    cy = sum(c[1] for c, r in circs) / n
    norm = []
    for i in range(n):
        (a, ra), (b, rb) = circs[i], circs[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = m.hypot(dx, dy)
        base = m.atan2(dy, dx)
        phi = m.acos(max(-1, min(1, (ra - rb) / d)))
        best = None
        for ang in (base + phi, base - phi):
            nx, ny = m.cos(ang), m.sin(ang)
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            score = (mx - cx) * nx + (my - cy) * ny
            if best is None or score > best[0]:
                best = (score, ang)
        norm.append(best[1])
    # edge i leaves circle i at angle norm[i] and arrives at circle i+1 at the same angle
    d_ = ''
    for i in range(n):
        (c, r) = circs[i]
        a_in = norm[i - 1]
        a_out = norm[i]
        while a_out < a_in:
            a_out += 2 * m.pi
        if i == 0:
            d_ += f"M{c[0] + r * m.cos(a_in):.4f} {c[1] + r * m.sin(a_in):.4f}"
        else:
            d_ += f"L{c[0] + r * m.cos(a_in):.4f} {c[1] + r * m.sin(a_in):.4f}"
        if r > 0 and a_out - a_in > 1e-6:
            d_ += arc_cmds(c[0], c[1], r, a_in, a_out)
    d_ += 'Z'
    return P(d_)


def lune(x, y_bottom, chord, t_mid, sag, soft=0.0):
    """closed-eye lid: the lower lune between two circular arcs through the same two tips.
    chord = tip-to-tip width, sag = how far the tips sit above the bottom, t_mid = thickness in the middle.
    soft > 0 rounds the tips (outset by soft with round joins; dimensions given are the final ones)."""
    import math as m
    from lib import stroke, U
    c = chord / 2 - soft
    s1 = sag            # lower arc sagitta (bottom to tip level)
    t = t_mid - 2 * soft
    yb = y_bottom - soft
    R1 = (c * c + s1 * s1) / (2 * s1)
    s2 = s1 - t          # how far the middle of the top edge sits below the tips: >0 crescent, <0 lens, 0 flat
    ty = yb - s1         # tip level
    a1 = m.asin(c / R1)
    d_ = f"M{x - c:.4f} {ty:.4f}"
    # lower arc: centre above, from left tip down through the bottom to the right tip (angles in y-down)
    cy1 = yb - R1
    d_ += arc_cmds(x, cy1, R1, m.pi / 2 + a1, m.pi / 2 - a1)
    if abs(s2) < 1e-6:
        d_ += f"L{x - c:.4f} {ty:.4f}Z"
    else:
        R2 = (c * c + s2 * s2) / (2 * abs(s2))
        a2 = m.asin(c / R2)
        if s2 > 0:   # top edge bows down too (crescent, tips point up)
            cy2 = (yb - t) - R2
            d_ += arc_cmds(x, cy2, R2, m.pi / 2 - a2, m.pi / 2 + a2)
        else:        # top edge bows up
            cy2 = (yb - t) + R2
            d_ += arc_cmds(x, cy2, R2, -m.pi / 2 + a2, -m.pi / 2 - a2)
        d_ += 'Z'
    p = P(d_)
    if soft > 0:
        p = U(p, stroke(p, 2 * soft))
    return p
