"""03-harakter - «щенок в буквах», round 3 (final polish).

The «о» of «дом» is a puppy: the ring is the head in the same ink as the word, two long ears grow out of
the top of the head and hang past the baseline, the counter is redrawn as a blaze (nose bridge + muzzle),
and the only coral of the logo sits inside the face.

Colour rule for every version:
  light grounds   word + head + ears = ink,   face + eyes = coral #FF967C (site button coral), nose = ink
  dark grounds    word + head + ears = cream, face + eyes = coral #FF967C,                     nose = ink
  mark            head + ears + nose = ink on a coral #FF967C tile, face + eyes = holes (the tile shows through)
  mono            everything ink, face + eyes knocked out, nose ink
Single source of truth for every deliverable. Run: python3 build.py
"""
import math, os
from geo import *
from fit import clean, stats
from puppy import puppy, spline
from spacing import gaps

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('OUT') or os.path.normpath(os.path.join(HERE, '..'))

# ---------------- palette ----------------
INK = '#141414'
CORAL = '#FF967C'      # = site buttons. Lives only inside the ink (or cream) head, so it needs no contrast with the page
CREAM = '#F3F2EF'
MUTED = '#6B6B6B'
MUTED_INV = '#A9A7A2'

# ---------------- type ----------------
FONT, WGHT, SIZE = 'Nunito[wght].ttf', int(os.environ.get('WGHT', 720)), 200
TEXT = 'домщенков.рф'
TRACK = -1.0
TAG_FONT, TAG_WGHT = 'Geist[wght].ttf', 500
TAG_TEXT = 'питомник щенков'
O_INDEX = 1
# spacing targets: mean horizontal gap over the x-height band (depth-capped), measured on the real outlines.
# д|о and о|м of the untouched font are 31 and 28; the ears take the place of the round sides of the «о».
TARGET_LEFT, TARGET_RIGHT, DEPTH = 31.0, 28.5, 40


def raw_word(size=SIZE, text=TEXT, kern=None, x=0.0, y=0.0):
    return shape(FONT, text, size, {'wght': WGHT}, TRACK * size / SIZE, kern, x, y)


def solve_kern():
    """kerning before / after the puppy so that the real gaps match the font's own rhythm,
    and the full stop centred between «в» and «р» (equal minimum gaps)"""
    gs, m = raw_word()
    xh = m['xheight']
    pup = puppy(gs[O_INDEX]['path'])['full']
    band = (-xh + 2, -2)
    k = {}
    g, _ = gaps(gs[0]['path'], pup, *band, depth=DEPTH)
    k[1] = TARGET_LEFT - _ if False else 0
    _, mean_l = gaps(gs[0]['path'], pup, *band, depth=DEPTH)
    k[1] = TARGET_LEFT - mean_l
    pup_s = move(pup, k[1], 0)
    _, mean_r = gaps(pup_s, move(gs[2]['path'], k[1], 0), *band, depth=DEPTH)
    k[2] = TARGET_RIGHT - mean_r
    # refine once (depth cap makes it slightly non-linear)
    for _i in range(2):
        _, ml = gaps(gs[0]['path'], move(pup, k[1], 0), *band, depth=DEPTH)
        k[1] += TARGET_LEFT - ml
        _, mr = gaps(move(pup, k[1], 0), move(gs[2]['path'], k[1] + k[2], 0), *band, depth=DEPTH)
        k[2] += TARGET_RIGHT - mr
    # full stop: equal min gaps to «в» and «р» measured over the dot's height
    dot = gs[9]['path']
    dy0, dy1 = dot.bounds[1] + 1, dot.bounds[3] - 1
    gl, _ = gaps(gs[8]['path'], dot, dy0, dy1)
    gr, _ = gaps(dot, gs[10]['path'], dy0, dy1)
    d = (gr - gl) / 2
    k[9], k[10] = d, -d
    return {i: round(v, 2) for i, v in k.items()}


KERN = solve_kern()


def word(x=0.0, y=0.0, size=SIZE, text=TEXT):
    k = {i: v * size / SIZE for i, v in KERN.items()}
    return raw_word(size, text, k, x, y)


def split_word(gs, o_index=O_INDEX):
    pup = puppy(gs[o_index]['path'])
    rest = union(*[g['path'] for i, g in enumerate(gs) if i != o_index and g['bbox']])
    return rest, pup


def tagline(x, baseline, xh_target, text=TAG_TEXT, track=0.03, centre=None):
    size = xh_target / 0.53  # Geist x-height = 0.53 em
    gs, m = shape(TAG_FONT, text, size, {'wght': TAG_WGHT}, size * track, None, x, baseline)
    t = union(*[g['path'] for g in gs if g['bbox']])
    if centre is not None:
        t = move(t, centre - (t.bounds[0] + t.bounds[2]) / 2, 0)
    return t


def frame(paths, pad, padx=None):
    b = [p.bounds for p in paths]
    x0, y0 = min(v[0] for v in b), min(v[1] for v in b)
    x1, y1 = max(v[2] for v in b), max(v[3] for v in b)
    px = pad if padx is None else padx
    return (x0 - px, y0 - pad, x1 - x0 + 2 * px, y1 - y0 + 2 * pad)


def write(name, s, where=OUT):
    with open(os.path.join(where, name), 'w') as f:
        f.write(s)


def puppy_layers(p, c_head, c_face, c_nose=INK):
    """c_face None -> face and eyes stay open (mono / mark)"""
    out = [(p['body'], c_head)]
    if c_face:
        out.append((p['face'], c_face))
    out.append((p['nose'], c_nose))
    return out


# ================= lockup =================
gs, m = word()
XH = m['xheight']
REST, PUP = split_word(gs)
d_left = gs[0]['path'].bounds[0]
desc_bottom = max(gs[0]['path'].bounds[3], gs[3]['path'].bounds[3])
TAG_XH = XH * 0.40
TAG = tagline(d_left + 2, desc_bottom + XH * 0.26 + TAG_XH, TAG_XH)


def lockup_svg(c_txt, c_face, c_tag, c_nose=INK, with_tag=True):
    layers = [(REST, c_txt)] + puppy_layers(PUP, c_txt, c_face, c_nose)
    paths = [REST, PUP['full']]
    if with_tag:
        layers.append((TAG, c_tag))
        paths.append(TAG)
    return svg(frame(paths, 12), layers)


write('lockup.svg', lockup_svg(INK, CORAL, MUTED))
write('lockup-inverse.svg', lockup_svg(CREAM, CORAL, MUTED_INV))
write('lockup-mono.svg', lockup_svg(INK, None, INK))
write('wordmark-only.svg', lockup_svg(INK, CORAL, MUTED, with_tag=False), HERE)


# ================= mark =================
def scale_pup(p, k):
    return {n: (v.transform(k, 0, 0, k, 0, 0) if n != 'center' else v) for n, v in p.items()}


def puppy_alone(size=100):
    """always built at the lockup size (200) so every version shares exactly the same outlines, then scaled"""
    g, _ = shape(FONT, 'о', SIZE, {'wght': WGHT})
    return scale_pup(puppy(g[0]['path']), size / SIZE)


def fit_radius(p, cx, cy, radius, dy=0.0):
    """scale the puppy so that every point of it lies within `radius` of (cx, cy) - the avatar-safe circle"""
    x0, y0, x1, y1 = p['full'].bounds
    hx, hy, _ = p['center']
    # sample the outline
    pts = []
    for verb, pp in p['full'].segments:
        for q in pp:
            pts.append(q)
    def far(k, oy):
        return max(math.hypot((x - (x0 + x1) / 2) * k, (y - (y0 + y1) / 2) * k + oy) for x, y in pts)
    k = 1.0
    for _ in range(40):
        f = far(k, dy)
        k *= radius / f
    ox, oy = cx - (x0 + x1) / 2 * k, cy - (y0 + y1) / 2 * k + dy
    return {n: (move(v.transform(k, 0, 0, k, 0, 0), ox, oy) if n != 'center' else v) for n, v in p.items()}


MP = fit_radius(puppy_alone(), 100, 100, 79, 4)
TILE = squircle(100, 100, 100, 46)
write('mark.svg', svg((0, 0, 200, 200), [(TILE, CORAL)] + puppy_layers(MP, INK, None)))
write('mark-mono.svg', svg(frame([MP['full']], 8), puppy_layers(MP, INK, None)))
write('mark-inverse.svg', svg((0, 0, 200, 200), [(TILE, INK)] + puppy_layers(MP, CREAM, CORAL)), HERE)


# ================= mark-16: drawn on the 16 px grid - head + ears silhouette, the blaze, a nose, no eyes =================
def mark16():
    """the same puppy reduced to what survives 16 px: a round head, two slender ears that hang lower than
    the chin, a thin slit that turns into a 1 px gap at 32 px (retina tabs), and the coral blaze with a nose"""
    tile = rrect(0, 0, 16, 16, 3.5)
    head = ellipse(8, 7.6, 5, 4.9)
    ear_l = spline([(5.0, 3.6), (2.8, 4.3), (1.3, 7.3), (1.0, 12.4), (2.1, 13.9), (3.3, 13.4), (3.5, 9.0)])
    slit_l = rrect(3.4, 9.0, 4.0, 15, 0.3)
    body = union(head, ear_l, mirror_x(ear_l, 8))
    body = diff(body, slit_l, mirror_x(slit_l, 8))
    blaze_ = union(rrect(7, 5.8, 9, 8.6, 1), rrect(5.5, 7.6, 10.5, 11.4, 1.8))
    nose_ = rrect(6.9, 8.3, 9.1, 9.7, 0.7)
    body = diff(body, blaze_)
    return svg((0, 0, 16, 16), [(tile, CORAL), (body, INK), (nose_, INK)])


write('mark-16.svg', mark16())


# ================= stacked: the puppy above the unbroken name, no plate =================
def stacked_parts():
    g2, m2 = word()
    r2, p2 = split_word(g2)
    line = union(r2, p2['full'])
    lx0, ly0, lx1, ly1 = line.bounds
    w = lx1 - lx0
    big = puppy_alone(100)
    bx0, by0, bx1, by1 = big['full'].bounds
    k = (w * 0.54) / (bx1 - bx0)
    cx = (lx0 + lx1) / 2
    top_of_word = min(gs_[1] for gs_ in [r2.bounds])
    head = {n: (move(v.transform(k, 0, 0, k, 0, 0), cx - (bx0 + bx1) / 2 * k, top_of_word - XH * 0.7 - by1 * k)
                if n != 'center' else v) for n, v in big.items()}
    txh = XH * 0.40
    tg = tagline(0, ly1 + XH * 0.30 + txh, txh, centre=cx)
    return head, r2, p2, tg


S_HEAD, S_REST, S_PUP, S_TAG = stacked_parts()


def stacked_plain_o():
    """comparison only: the puppy above, a plain «о» in the name"""
    g2, _ = word()
    rest = union(*[g['path'] for g in g2 if g['bbox']])
    paths = [S_HEAD['full'], rest, S_TAG]
    return svg(frame(paths, 18), puppy_layers(S_HEAD, INK, CORAL) + [(rest, INK), (S_TAG, MUTED)])


write('stacked-alt-plain-o.svg', stacked_plain_o(), HERE)


def stacked_svg(c_txt, c_face, c_tag, c_nose=INK, pad=18):
    paths = [S_HEAD['full'], S_REST, S_PUP['full'], S_TAG]
    layers = (puppy_layers(S_HEAD, c_txt, c_face, c_nose) + [(S_REST, c_txt)] +
              puppy_layers(S_PUP, c_txt, c_face, c_nose) + [(S_TAG, c_tag)])
    return svg(frame(paths, pad), layers)


write('stacked.svg', stacked_svg(INK, CORAL, MUTED))
write('stacked-inverse.svg', stacked_svg(CREAM, CORAL, MUTED_INV))


# ================= extras =================
def text_on_arc(text, cx, cy, radius, size, centre_deg, bottom=False, wght=WGHT, font=FONT, track=0.0, var=None):
    """top text reads clockwise (glyph tops outward); bottom text reads left-to-right (glyph tops inward)"""
    gs_, _ = shape(font, text, size, var or {'wght': wght}, track)
    total = gs_[-1]['x'] + gs_[-1]['advance'] - gs_[0]['x']
    out = []
    for g in gs_:
        if not g['bbox']:
            continue
        xc = g['x'] + g['advance'] / 2 - total / 2
        p = move(g['path'], -(g['x'] + g['advance'] / 2), 0)
        if not bottom:
            theta = centre_deg + math.degrees(xc / radius)
            p = rotate(p, theta)
        else:
            theta = centre_deg - math.degrees(xc / radius)
            p = rotate(p, theta - 180)
        t = math.radians(theta)
        out.append(move(p, cx + radius * math.sin(t), cy - radius * math.cos(t)))
    return union(*out)


def collar_tag():
    body = circle(150, 176, 128)
    tab = rrect(118, 22, 182, 96, 30)
    hole = circle(150, 50, 13)
    tag = clean(diff(union(body, tab), hole), tol=0.02, fillet=(0, 6), window=1.5, thresh=30)
    p = fit_radius(puppy_alone(), 150, 162, 74)
    bot = text_on_arc('домщенков.рф', 150, 176, 104, 25, 180, bottom=True, track=0.6)
    bot = clean(bot, tol=0.015, window=0.4, thresh=35)
    return svg(frame([tag], 6), [(tag, CORAL)] + puppy_layers(p, INK, None) + [(bot, INK)])


def pattern():
    """«find the puppy»: a field of ink «о» letters; at a second look five of them have ears and a coral face"""
    g, _ = shape(FONT, 'о', 100, {'wght': WGHT})
    o = g[0]['path']
    pp = puppy_alone(100)
    ob = o.bounds
    ocx, ocy = (ob[0] + ob[2]) / 2, (ob[1] + ob[3]) / 2
    cols, rows, step_x, step_y = 9, 6, 100, 100
    W, H = cols * step_x, rows * step_y
    pups = {(2, 1), (6, 0), (4, 3), (7, 4), (1, 5)}
    plain, bodies, face, nose_ = [], [], [], []
    for r in range(rows):
        for c in range(cols):
            x = (c + 0.5) * step_x + (step_x / 2 if r % 2 else 0) - step_x / 4
            y = (r + 0.5) * step_y
            if (c, r) in pups:
                bodies.append(move(pp['body'], x - ocx, y - ocy))
                face.append(move(pp['face'], x - ocx, y - ocy))
                nose_.append(move(pp['nose'], x - ocx, y - ocy))
            else:
                plain.append(move(o, x - ocx, y - ocy))
    bg = rrect(0, 0, W, H, 36)
    clip = lambda p: inter(p, bg)
    # puppies sit fully inside the card, so only the plain letters are clipped; each layer is one path
    pup_ink = Path()
    for b_ in bodies:
        pup_ink.addPath(b_)
    pup_face = Path()
    for f_ in face:
        pup_face.addPath(f_)
    pup_nose = Path()
    for n_ in nose_:
        pup_nose.addPath(n_)
    return svg((0, 0, W, H), [(bg, CREAM), (clip(union(*plain)), INK), (pup_ink, INK), (pup_face, CORAL), (pup_nose, INK)])


write('extra-collar-tag.svg', collar_tag())
write('extra-pattern.svg', pattern())

if __name__ == '__main__':
    print('kern', KERN)
    print('puppy body segs/lines/shortest', stats(PUP['body']), 'face', stats(PUP['face']), 'nose', stats(PUP['nose']))
    lb = frame([REST, PUP['full'], TAG], 12)
    print('lockup ratio %.2f' % (lb[2] / lb[3]))
    print('built', OUT)
