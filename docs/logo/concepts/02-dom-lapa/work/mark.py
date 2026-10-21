"""The «дом-лапа» glyph: the main pad of a puppy paw is a little house; the door is the
natural notch at the bottom of a pad; the four toes fan around the roof with an even gap.
v3: the door is the house itself at 0.36 scale (same 37° pitch): «дом в доме» — the one ownable trait."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geo import *

P = dict(
    W=100,          # pad (house) width
    H=92,           # pad height, apex to base
    pitch=37,       # roof pitch, degrees
    r_apex=18, r_eave=13, r_base=26,
    door='house',   # v3: 'house' = the door is a scaled copy of the house (same pitch); 'arch' = v2 arch
    door_k=0.36,    # door = house x 0.36 (36 x 33 in the 200 grid)
    door_apex=11,   # optical: a negative apex looks sharper than a positive one, so rounder than 18 x 0.36 = 6.5
    door_eave=6,    # same reason: 13 x 0.36 = 4.7 looked pinched at 400 px
    door_w=32, door_h=34,   # v2 arch (kept for comparison sheets)
    gap=13,         # ONE gap for everything: toe-pad 13, toe-toe 12-13 (survives 16 px)
    fan=(0, 112),   # fan centre (relative x, absolute y in 200 box)
    inner=dict(a=22, rx=15.5, far=17, near=19.5, tilt=-1),
    outer=dict(a=63, rx=14.5, far=15.5, near=18.5, tilt=-8),
    jamb=7,         # door feet rounded like the lobes of a pad, not pinched
)


def pad_shape(p=P, base=172, cx=100):
    W, H = p['W'], p['H']
    x0, x1 = cx - W / 2, cx + W / 2
    top = base - H
    eave = top + (W / 2) * math.tan(math.radians(p['pitch']))
    pad = rpoly([(cx, top), (x1, eave), (x1, base), (x0, base), (x0, eave)],
                [p['r_apex'], p['r_eave'], p['r_base'], p['r_base'], p['r_eave']])
    if p.get('door', 'arch') == 'house':
        k = p['door_k']
        dw, dh = W * k, H * k
        dtop = base - dh
        deave = dtop + (dw / 2) * math.tan(math.radians(p['pitch']))
        door = rpoly([(cx, dtop), (cx + dw / 2, deave), (cx + dw / 2, base + 40), (cx - dw / 2, base + 40), (cx - dw / 2, deave)],
                     [p['door_apex'], p['door_eave'], 0, 0, p['door_eave']])
    else:
        dw, dh = p['door_w'], p['door_h']
        door = rrect(cx - dw / 2, base - dh, dw, dh + 40, dw / 2)
    return pad, door


def place(toe_fn, pad_grown, cx, cy, ang, tilt=0.0):
    """slide a toe along the ray (from fan centre, angle from vertical) until it clears pad_grown."""
    a = math.radians(ang)
    ux, uy = math.sin(a), -math.cos(a)
    lo, hi = 0.0, 200.0
    for _ in range(40):
        mid = (lo + hi) / 2
        t = toe_fn(cx + ux * mid, cy + uy * mid, ang + tilt)
        if inter(t, pad_grown).area > 1e-3:
            lo = mid
        else:
            hi = mid
    return toe_fn(cx + ux * hi, cy + uy * hi, ang + tilt), (cx + ux * hi, cy + uy * hi)


def glyph(p=P, with_door=True):
    cx = 100
    pad, door = pad_shape(p, cx=cx)
    pad_full = union(pad)
    grown = grow(pad_full, p['gap'])
    fx, fy = cx + p['fan'][0], p['fan'][1]
    toes = []
    centres = []
    for key in ('inner', 'outer'):
        q = p[key]
        fn = lambda x, y, a, q=q: egg(x, y, q['rx'], q['far'], q['near'], a)
        t, c = place(fn, grown, fx, fy, -q['a'], -q.get('tilt', 0))
        toes.append(t); centres.append(c)
    toes += [mirror_x(t, cx) for t in toes]
    body = diff(pad, door) if with_door else union(pad)
    if p.get('jamb', 0):
        body = grow(shrink(body, p['jamb']), p['jamb'])   # opening: softens the door-jamb corners only
    shape = union(body, *toes)
    return shape, dict(toes=toes, pad=pad, door=door, centres=centres)


def normalised(p=P, size=100, with_door=True):
    """glyph scaled so that its bbox fits a size x size box, centred (optical centre handled by caller)."""
    g, info = glyph(p, with_door)
    b = bounds(g)
    s = size / max(b[2] - b[0], b[3] - b[1])
    g = xf(g, s, 0, 0, s, -b[0] * s + (size - (b[2] - b[0]) * s) / 2, -b[1] * s + (size - (b[3] - b[1]) * s) / 2)
    return g


if __name__ == '__main__':
    g, info = glyph()
    b = bounds(g)
    print('bbox', [round(v, 1) for v in b], 'w/h', round((b[2] - b[0]) / (b[3] - b[1]), 3))
    # toe-toe gaps
    t = info['toes']
    import itertools
    def gapof(a, c):
        lo, hi = 0, 30
        for _ in range(25):
            mid = (lo + hi) / 2
            if inter(grow(a, mid / 2), grow(c, mid / 2)).area > 1e-3: hi = mid
            else: lo = mid
        return lo
    print('inner-outer gap', round(gapof(t[0], t[1]), 2), 'inner-inner', round(gapof(t[0], t[2]), 2))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mark_big.svg')
    open(out, 'w').write(svg((b[0] - 10, b[1] - 10, b[2] - b[0] + 20, b[3] - b[1] + 20), path_el(g, '#141414')))
