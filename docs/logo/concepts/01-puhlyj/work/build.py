"""«Пухлый» v3 — домщенков.рф. One source of truth for every deliverable.

Run:  python3 build.py   -> writes every SVG into the concept folder and prints a short report.
Units: the wordmark is set at size 100 (Nunito wght 860), baseline y = 0, y grows downward.
Geometry: wm.py (letters from the font's own outlines + explicit node edits + clean corner fillets,
the house, the descriptor), lib.py (booleans, shapes, SVG output).
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from wm import *  # noqa

OUT = os.path.dirname(HERE)

# ---------------------------------------------------------------- palette
NAVY = '#0F3A63'    # brand colour: letters on light backgrounds; background of social, print, footer
CREAM = '#ECE8DF'   # letters on dark
INK = '#141414'     # single-colour version only (the site's ink)
CORAL = '#FF6F4F'   # the house in the «о» (strong coral of the site), the only accent
WHITE = '#FFFFFF'   # sticker die-cut border only

# ---------------------------------------------------------------- wordmark
P = dict(
    wght=860,                  # one step lighter than v2 (1000 + inflation): reads as lowercase text, not a block
    fillet=3.0,                # inner joins and counter corners rounded with true arcs (no erosion / dilation)
    track=-3.2,
    kern={'до': -1.4, 'ом': 0.4, 'мщ': 1.6, 'ще': -0.4, 'ен': 0.0, 'нк': 1.4, 'ко': -1.0, 'ов': 0.0},
    # hand edits, in letter units (wm.edit_letter): «д» and «щ» get proper lowercase descenders (as long as «р»),
    # the counters of «м щ н д в» are a little narrower (stems, joins and round ends untouched)
    edits={'д': {'down': 5.0, 'squeeze': 0.88}, 'щ': {'down': 5.0, 'squeeze': 0.82},
           'м': {'squeeze': 0.90}, 'н': {'squeeze': 0.92}, 'в': {'squeeze': 0.90}},
    tail=0.50, tail_gap=0.6, tail_kern={'.р': 0.6, 'рф': 0.4},
    # the house standing inside the «о» of «дом» (fractions of the «о» outer box) with ONE trait: a chimney
    house=dict(w=0.56, floor=0.20, wall=0.25, roof=0.30, r_peak=4.2, r_eave=3.0, r_base=3.2,
               trait='chimney', ch_at=(0.50, 0.0), ch_w=0.18, ch_top=0.22, r_ch=1.5, r_ch_in=1.0),
)
# softer steps where the stems of «д» meet its feet (the font draws a small shoulder there)
FILLET_AT.update({'д': [((3.0, -17.0, 13.0, -8.0), 5.0), ((49.0, -17.0, 59.0, -8.0), 5.0)]})
TAG = dict(text='питомник щенков', wght=500, size=55.0, gap=17.0)   # Geist 500, lowercase, no letter-spacing
AVATAR = dict(width=0.64, dy=4.0)
STACK = dict(align='centre', fill=0.80, leading=88.0, tag=46.0, tag_gap=16.0)


def build_wordmark(p=P):
    w = wordmark(p)
    return w


def word_only_width(w):
    """ink width of «домщенков» (without «.рф»)"""
    return union(*[q for _, q, _ in w['letters']]).bounds


def build_tagline(text=TAG['text'], size=TAG['size']):
    return tagline(text, size, TAG['wght'])


def mark_parts(p=P):
    """the «о» of «дом» alone (pebble + house), centred on (0,0), width 1.0"""
    letters, _ = run('о', 100.0, p['wght'], 0, {}, {}, fil=p.get('fillet', 0.0))
    outer = o_outer(letters[0][1])
    hs = house_in_o(outer, p['house'])
    ob = outer.bounds
    cx, cy = (ob[0] + ob[2]) / 2, (ob[1] + ob[3]) / 2
    ow = ob[2] - ob[0]
    T = lambda q: scale(translate(q, -cx, -cy), 1.0 / ow)
    return T(outer), T(hs)


def place(p, s, x, y):
    return translate(scale(p, s), x, y)


def centre_x(p, cx):
    b = p.bounds
    return translate(p, cx - (b[0] + b[2]) / 2, 0)


def write(name, layers, box, pad=0.0):
    s, vb = svg_doc(layers, box, pad)
    with open(os.path.join(OUT, name), 'w') as fh:
        fh.write(s)
    return vb


def fill_holes(p):
    p = simplify(p)
    cs = list(p.contours)
    big = max(cs, key=lambda c: abs(c.area))
    return union(*[simplify(c) for c in cs if c.clockwise == big.clockwise])


def lockup_parts():
    w = build_wordmark()
    word, tail, hs = w['word'], w['tailp'], w['house']
    wb = bounds_union(word, tail)
    tag = build_tagline()
    tb = tag.bounds
    tag = translate(tag, wb[0] - tb[0], wb[3] + TAG['gap'] - tb[1])     # left edge on the left foot of «д»
    return w, word, tail, hs, tag, TAG['size']


def stacked_layers(align=None, S=1000.0, fill=None):
    """«дом» / «щенков.рф» / descriptor, cream on a navy square. Splitting the name on two lines spells it out:
    «дом щенков». The house appears once (in «дом»)."""
    align = align or STACK['align']
    fill = fill or STACK['fill']
    E = P['edits']
    l1, e1 = run('дом', 100.0, P['wght'], P['track'], P['kern'], E, fil=P['fillet'])
    l2, e2 = run('щенков', 100.0, P['wght'], P['track'], P['kern'], E, fil=P['fillet'])
    outer = o_outer(l1[1][1])
    hs2 = house_in_o(outer, P['house'])
    dom = union(l1[0][1], diff(outer, hs2), l1[2][1])
    T = P['tail']
    t2, _ = run('.рф', 100.0 * T, P['wght'], P['track'] * T, P['tail_kern'], E, e2 + P['tail_gap'], 0.0, fil=P['fillet'])
    sch = union(*[q for _, q, _ in l2])
    rf = union(*[q for _, q, _ in t2])
    LG = STACK['leading']                         # baseline to baseline
    sch, rf = translate(sch, 0, LG), translate(rf, 0, LG)
    line2 = bounds_union(sch, rf)
    tg = tagline(TAG['text'], STACK['tag'], TAG['wght'])
    tgb = tg.bounds
    tg = translate(tg, 0, line2[3] + STACK['tag_gap'] - tgb[1])
    if align == 'centre':
        cx = (line2[0] + line2[2]) / 2
        # «дом» and its house move together
        db = union(l1[0][1], outer, l1[2][1]).bounds
        dx = cx - (db[0] + db[2]) / 2
        dom = translate(union(l1[0][1], diff(outer, hs2), l1[2][1]), dx, 0)
        hs2 = translate(hs2, dx, 0)
        tg = centre_x(tg, cx)
    else:
        tg = translate(tg, line2[0] - tg.bounds[0], 0)
    blk = bounds_union(dom, sch, rf, tg)
    bw, bh = blk[2] - blk[0], blk[3] - blk[1]
    k = S * fill / bw
    def fit(q):
        return translate(scale(q, k), S / 2 - (blk[0] + bw / 2) * k, S / 2 - (blk[1] + bh / 2) * k)
    bg = rrect(0, 0, S, S, S * 0.08)
    return [(bg, NAVY), (fit(union(dom, hs2)), CREAM), (fit(hs2), CORAL), (fit(sch), CREAM), (fit(rf), CREAM), (fit(tg), CREAM)]


# ---------------------------------------------------------------- compositions
def build():
    info = {}
    w, word, tail, hs, tag, tsize = lockup_parts()
    solid = union(word, hs)                      # colour files: the house is painted over a solid «о» (no seam)
    box = bounds_union(word, tail, tag)
    vb = write('lockup.svg', [(solid, NAVY), (tail, NAVY), (tag, NAVY), (hs, CORAL)], box, 0)
    write('lockup-inverse.svg', [(word, CREAM), (tail, CREAM), (tag, CREAM)], box, 0)   # house = cut-out, as the paw in the reference
    write('lockup-mono.svg', [(word, INK), (tail, INK), (tag, INK)], box, 0)
    info['lockup_ratio'] = round(vb[2] / vb[3], 2)
    info['lockup_px_at_40'] = round(40 * vb[2] / vb[3])
    info['tag_size_pct'] = round(tsize, 1)

    # ---- mark: the «о» of «дом» alone, a navy pebble with the coral house (two shapes, no tile: no «target» at 16 px)
    o1, h1 = mark_parts()
    MO = 92.0
    o_m, h_m = place(o1, MO, 50, 50), place(h1, MO, 50, 50)
    ob = o_m.bounds
    oy = 50 - (ob[1] + ob[3]) / 2
    o_m, h_m = translate(o_m, 0, oy), translate(h_m, 0, oy)
    write('mark.svg', [(union(o_m, h_m), NAVY), (h_m, CORAL)], (0, 0, 100, 100), 0)
    write('mark-mono.svg', [(diff(o_m, h_m), INK)], (0, 0, 100, 100), 0)
    info['mark_o_box'] = [round(v, 1) for v in o_m.bounds]
    info['mark_house_box'] = [round(v, 1) for v in h_m.bounds]

    # ---- stacked (square formats): «дом» over «щенков.рф», descriptor below, cream on navy
    write('stacked.svg', stacked_layers(), (0, 0, 1000, 1000), 0)

    # ---- extra 0: social avatar — the whole word «дом» (self-standing, readable from ~40 px), full-bleed navy square;
    # platforms crop it to a circle, so the word sits inside the central 64 %
    S = 1000.0
    E = P['edits']
    l1, _ = run('дом', 100.0, P['wght'], P['track'], P['kern'], E, fil=P['fillet'])
    outer = o_outer(l1[1][1])
    hs3 = house_in_o(outer, P['house'])
    dom = union(l1[0][1], diff(outer, hs3), l1[2][1])
    db = dom.bounds
    k = S * AVATAR['width'] / (db[2] - db[0])
    cy = (-48.4 + 0.0) / 2 + AVATAR['dy']                     # optical centre: middle of the x-height band, nudged down
    def fa(q):
        return translate(scale(q, k), S / 2 - (db[0] + db[2]) / 2 * k, S / 2 - cy * k)
    write('extra-avatar.svg', [(rect(0, 0, S, S), NAVY), (fa(union(dom, hs3)), CREAM), (fa(hs3), CORAL)], (0, 0, S, S), 0)

    # ---- extra 1: die-cut sticker of the wordmark (navy body, white kiss-cut border)
    sw = union(word, tail)
    base = fill_holes(thicken(fill_holes(sw), 30))
    border = fill_holes(thicken(base, 22))
    write('extra-sticker.svg', [(border, WHITE), (base, NAVY), (solid, CREAM), (tail, CREAM), (hs, CORAL)], border.bounds, 3)

    # ---- extra 2: puppy passport cover (documents folder: vet passport, РКФ metric, contract)
    PW, PH = 700.0, 990.0
    cover = rrect(0, 0, PW, PH, 30)
    kk = PW * 0.74 / (box[2] - box[0])
    parts = [scale(q, kk) for q in (solid, tail, tag, hs)]
    fb = bounds_union(*parts)
    dx, dy = PW / 2 - (fb[0] + fb[2]) / 2, PH * 0.40 - (fb[1] + fb[3]) / 2
    solid_p, tail_p, tag_p, hs_p = [translate(q, dx, dy) for q in parts]
    def small(text, width, cx, y_top):
        t = tagline(text, 100.0, 500)
        b = t.bounds
        t = scale(t, width / (b[2] - b[0]))
        b = t.bounds
        return translate(t, cx - (b[0] + b[2]) / 2, y_top - b[1])
    top = small('паспорт щенка', PW * 0.30, PW / 2, PH * 0.075)
    px0, px1, py0, py1 = PW * 0.14, PW * 0.86, PH * 0.70, PH * 0.84
    plate = rrect(px0, py0, px1, py1, 22)
    nm = tagline('кличка', 100.0, 500)
    nb = nm.bounds; nm = scale(nm, PW * 0.11 / (nb[2] - nb[0])); nb = nm.bounds
    nm = translate(nm, px0 + 30 - nb[0], py0 + 26 - nb[1])
    line = rrect(px0 + 30, py1 - 34, px1 - 30, py1 - 31, 1.5)
    foot = small('растим дома · москва', PW * 0.30, PW / 2, PH * 0.905)
    write('extra-passport.svg', [(cover, NAVY), (top, CREAM), (solid_p, CREAM), (tail_p, CREAM), (hs_p, CORAL), (tag_p, CREAM),
                                 (plate, CREAM), (nm, NAVY), (line, NAVY), (foot, CREAM)], (0, 0, PW, PH), 0)
    return info


if __name__ == '__main__':
    print(json.dumps(build()))
