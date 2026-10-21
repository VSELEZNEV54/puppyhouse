#!/usr/bin/env python3
"""02-dom-lapa «Дом-лапа» — single source of truth for every deliverable.
python3 build.py  -> writes ../lockup.svg, ../lockup-inverse.svg, ../lockup-short.svg, ../mark.svg,
                     ../lockup-mono.svg, ../mark-mono.svg, ../stacked.svg, ../extra-*.svg
v3: door = the house at 0.36 (mark.py), «д» with a roof (d_with_roof), mark coral #DF5838,
    extra-phone.svg (lockup-short in a 1:1 phone header), extra-on-coral.svg (mono-on-coral rule).
needs: pip install skia-pathops (geometry in geo.py), glyph construction in mark.py.
"""
import sys, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geo import *
import mark as M

OUT = os.path.normpath(os.path.join(HERE, '..'))

# ---------------------------------------------------------------- colours (site palette)
INK = '#141414'
PAGE = '#F3F2EF'
CORAL = '#FF967C'        # tile = site button coral
CORAL_STRONG = '#FF6F4F'
CORAL_DEEP = '#DF5838'   # v3: THE mark colour on light backgrounds: 3.36:1 on #F3F2EF, 3.76:1 on white (v2 #E8603F = 3.04, no margin)
MUTED = '#6B6B6B'        # tagline on light
MUTED_INV = '#A8A49D'    # tagline on ink / navy
NAVY = '#10375C'

# ---------------------------------------------------------------- the glyph
GLYPH = M.normalised(size=100)          # paw-house, bbox fits 100x100, centred in it
GB = bounds(GLYPH)


def glyph_at(cx, cy, size, dy=0.0):
    """glyph whose bbox max side = size, centred at (cx, cy)."""
    s = size / 100
    return xf(GLYPH, s, 0, 0, s, cx - 50 * s, cy - 50 * s + dy * s)


def tile(x, y, s):
    return rrect(x, y, s, s, s * 0.235, smooth=1.35)


TILE_GLYPH = 0.78     # glyph size relative to tile (v1 0.74): +1 px of toe at 16 px, still inside the central 80 %
TILE_DY = -1.2        # optical: lift the glyph a hair (the house body is heavier than the toes)

# ---------------------------------------------------------------- wordmark
WM_FONT = 'Rubik[wght].ttf'
WM_VAR = {'wght': 490}
WM_TRACK = -18 / 1000          # em
# manual kerning, em/1000, applied before the second glyph of the pair
KERN = {
    'до': -2, 'ом': 0, 'мщ': -6, 'ще': -6, 'ен': -4, 'нк': -8, 'ко': -6, 'ов': 0,
    'в.': -34, '.р': -40, 'рф': 4,
}
TAG_FONT = 'Geist[wght].ttf'
TAG_VAR = {'wght': 500}
TAG_TRACK = 14 / 1000
XH = 0.52                      # Rubik x-height / em (measured: 520/1000)


def line(font, var, txt, size, track, kern=None, edit=None):
    """returns (path, ink bbox, advance). baseline y=0, origin x=0.
    edit: {char: fn(path_at_1000_units_origin_0) -> path} to redraw single letters."""
    t = text(font, txt, size, var)
    out = []
    extra = 0.0
    prev = None
    for g in t['glyphs']:
        ch = g['char']
        if prev is not None:
            extra += track * size + (kern or {}).get(prev + ch, 0) / 1000 * size
        p = g['path']
        if edit and ch in edit:
            k = 1000 / size
            p = move(p, -g['x'], 0)
            p = xf(edit[ch](xf(p, k, 0, 0, k, 0, 0)), 1 / k, 0, 0, 1 / k, g['x'], 0)
        out.append(move(p, extra, 0))
        prev = ch
    p = union(*out)
    return p, bounds(p), t['advance'] + extra


# ---------------------------------------------------------------- wordmark signature: «д» with a roof
# The first letter of «дом» gets a gentle gable: the apex stays on the x-height, the two top corners
# drop by D_ROOF, the bar keeps its thickness, so the counter of «д» becomes a small negative house,
# the same «дом в доме» as the door of the mark. Measured from Rubik 490 at 1000 units.
D_ROOF = 62          # eave drop, 1000 units (~12 % of the x-height)
D_APEX_R = 44
D_OVER = 14          # the rounded apex peaks at -530, level with the overshoot of «о» (a pointed top needs it too)


def _d_metrics():
    t = text(WM_FONT, 'д', 1000, WM_VAR)['glyphs'][0]
    subs = [sp for sp in t['d'].split('Z') if sp.strip()]
    outer, inner = parse(subs[0] + 'Z'), parse(subs[1] + 'Z')
    ob, ib = bounds(outer), bounds(inner)
    top_pts = [pt for pt in outer.points if pt[1] < ob[1] + 30]
    xl, xr = min(p[0] for p in top_pts), max(p[0] for p in top_pts)
    ctop = [pt for pt in inner.points if abs(pt[1] - ib[1]) < 0.5]
    cl, cr = min(p[0] for p in ctop), max(p[0] for p in ctop)
    return xl, xr, ob[1], ib[1], cl, cr


def d_with_roof(gp, drop=D_ROOF, r_apex=D_APEX_R, over=D_OVER):
    xl, xr, yt, yc, cl, cr = _d_metrics()
    cx = (xl + xr) / 2
    ya = yt - over                                    # apex
    k = (drop + over) / (cx - xl)
    th = yc - yt                                     # bar thickness, kept constant
    keep = inter(gp, rrect(-200, yc + 30, 1200, 900, 0))       # the letter below the bar
    outer = rpoly([(xl, yc + 40), (xl, yt + drop), (cx, ya), (xr, yt + drop), (xr, yc + 40)],
                  [0, 23.9, r_apex, 23.9, 0])                   # 23.9 = Rubik's own corner radius
    ytop = lambda x: ya + k * abs(x - cx) + th
    inner = rpoly([(cl, yc + 60), (cl, ytop(cl)), (cx, ytop(cx)), (cr, ytop(cr)), (cr, yc + 60)],
                  [0, 0, r_apex * 0.4, 0, 0])
    return union(keep, diff(outer, inner))


WM_EDIT = {'д': d_with_roof}


def wordmark(size):
    return line(WM_FONT, WM_VAR, 'домщенков.рф', size, WM_TRACK, KERN, WM_EDIT)


def tagline(size):
    return line(TAG_FONT, TAG_VAR, 'питомник щенков', size, TAG_TRACK)


# ---------------------------------------------------------------- compositions
# horizontal lockup, units: glyph ink height = 100.
NAME_SIZE = 56           # bigger name than v1 (50): ~20.7 px in a 40 px header
TAG_SIZE = 27            # ~10 px in a 40 px header (v1: 8.9 px)
LEAD = 41                # name baseline -> tagline baseline
GAP = 21                 # glyph -> text
BLOCK_CY = 57            # optical centre of the glyph (house is heavier than the toes)
TAG_DX = 1.5             # tagline nudged right: «п» stem aligns with the stem of «д», not its foot
PAD = 4


def glyph_box(top, bottom):
    """glyph scaled so its ink spans top..bottom; returns path and its bbox."""
    gh = GB[3] - GB[1]
    s = (bottom - top) / gh
    g = xf(GLYPH, s, 0, 0, s, -GB[0] * s, top - GB[1] * s)
    return g, bounds(g)


def lockup_parts(glyph_fill, name_fill, tag_fill):
    """[(path, fill)], viewBox"""
    wp, wb, _ = wordmark(NAME_SIZE)
    tp, tb, _ = tagline(TAG_SIZE)
    g, gb = glyph_box(0, 100)
    xh = NAME_SIZE * XH
    # text block = x-height top of the name .. tagline baseline, centred on the glyph's optical centre
    b1 = BLOCK_CY - (LEAD - xh) / 2
    b2 = b1 + LEAD
    x0 = gb[2] + GAP
    parts = [(g, glyph_fill), (move(wp, x0 - wb[0], b1), name_fill), (move(tp, x0 - tb[0] + TAG_DX, b2), tag_fill)]
    right = max(x0 + wb[2] - wb[0], x0 + tb[2] - tb[0] + TAG_DX)
    top = min(gb[1], b1 + wb[1])
    bottom = max(gb[3], b1 + wb[3], b2 + tb[3])
    vb = (-PAD, top - PAD, right + 2 * PAD, bottom - top + 2 * PAD)
    return parts, vb


def lockup(glyph_fill, name_fill, tag_fill):
    parts, vb = lockup_parts(glyph_fill, name_fill, tag_fill)
    return svg(vb, ''.join(path_el(p, f) for p, f in parts)), vb


def fit(parts, vb, x, y, h):
    """place parts so that their viewBox is h tall with its top-left corner at (x, y); returns [(path, fill)], width."""
    k = h / vb[3]
    return [(xf(p, k, 0, 0, k, x - vb[0] * k, y - vb[1] * k), f) for p, f in parts], vb[2] * k


SHORT_SIZE = 64
SHORT_GAP = 24


def lockup_short_parts(glyph_fill, name_fill):
    """one line, no tagline: phone header, small placements, watermark."""
    wp, wb, _ = wordmark(SHORT_SIZE)
    g, gb = glyph_box(0, 100)
    xh = SHORT_SIZE * XH
    base = BLOCK_CY + 3 + xh / 2          # x-height band centred a hair below the glyph's optical centre (on the house)
    x0 = gb[2] + SHORT_GAP
    parts = [(g, glyph_fill), (move(wp, x0 - wb[0], base), name_fill)]
    right = x0 + wb[2] - wb[0]
    top = min(gb[1], base + wb[1]); bottom = max(gb[3], base + wb[3])
    vb = (-PAD, top - PAD, right + 2 * PAD, bottom - top + 2 * PAD)
    return parts, vb


def lockup_short(glyph_fill, name_fill):
    parts, vb = lockup_short_parts(glyph_fill, name_fill)
    return svg(vb, ''.join(path_el(p, f) for p, f in parts)), vb


def mark_svg(tile_fill=CORAL, glyph_fill=INK):
    body = path_el(tile(0, 0, 100), tile_fill) + path_el(glyph_at(50, 50, 100 * TILE_GLYPH, TILE_DY), glyph_fill)
    return svg((0, 0, 100, 100), body)


def mark_mono():
    g = glyph_at(50, 50, 100)
    b = bounds(g)
    p = 4
    return svg((b[0] - p, b[1] - p, b[2] - b[0] + 2 * p, b[3] - b[1] + 2 * p), path_el(g, INK))


def stacked(card=CORAL, fg=INK, tagc=INK):
    """square card for social posts / stickers: works on any background."""
    S = 600
    wsize = 76
    wp, wb, _ = wordmark(wsize)
    tp, tb, _ = tagline(34)
    els = [path_el(rrect(0, 0, S, S, S * 0.16, smooth=1.3), card)]
    gw = 236
    s = gw / (GB[2] - GB[0])
    gh = (GB[3] - GB[1]) * s
    nb_rel = gh + 50 + wsize * XH          # glyph top -> name baseline
    tb_rel = nb_rel + 50                   # -> tagline baseline
    total = tb_rel                         # glyph top .. tagline baseline
    gtop = (S - total) / 2 - 6
    els.append(path_el(xf(GLYPH, s, 0, 0, s, S / 2 - (GB[0] + GB[2]) / 2 * s, gtop - GB[1] * s), fg))
    els.append(path_el(move(wp, S / 2 - (wb[0] + wb[2]) / 2, gtop + nb_rel), fg))
    els.append(path_el(move(tp, S / 2 - (tb[0] + tb[2]) / 2, gtop + tb_rel), tagc))
    return svg((0, 0, S, S), ''.join(els))


# ---------------------------------------------------------------- applications
NAVY_LINE = '#24507A'
PEACH = '#F1BC94'


def glyph_w(cx, top, width):
    s = width / (GB[2] - GB[0])
    return xf(GLYPH, s, 0, 0, s, cx - (GB[0] + GB[2]) / 2 * s, top - GB[1] * s), (GB[3] - GB[1]) * s


def centred(p, b, cx, base):
    return move(p, cx - (b[0] + b[2]) / 2, base)


def extra_passport():
    """puppy passport cover (navy, coral glyph, cream wordmark) + coral collar tag."""
    W, H = 400, 560
    els = [path_el(rrect(0, 0, W, H, 30, smooth=1.2), NAVY)]
    frame = diff(rrect(22, 22, W - 44, H - 44, 18, smooth=1.2), rrect(25, 25, W - 50, H - 50, 15, smooth=1.2))
    els.append(path_el(frame, NAVY_LINE))
    lp, lb, _ = line(TAG_FONT, TAG_VAR, 'паспорт щенка', 17, 120 / 1000)
    els.append(path_el(centred(lp, lb, W / 2, 84), MUTED_INV))
    g, gh = glyph_w(W / 2, 168, 150)
    els.append(path_el(g, CORAL))
    wp, wb, _ = wordmark(42)
    els.append(path_el(centred(wp, wb, W / 2, 168 + gh + 72), PAGE))
    tp, tb, _ = line(TAG_FONT, TAG_VAR, 'питомник щенков · москва', 16, 40 / 1000)
    els.append(path_el(centred(tp, tb, W / 2, 168 + gh + 108), MUTED_INV))
    rule = rrect(80, H - 92, W - 160, 1.5, 0.75)
    els.append(path_el(rule, NAVY_LINE))
    np_, nb, _ = line(TAG_FONT, TAG_VAR, 'кличка · порода · дата рождения', 14, 30 / 1000)
    els.append(path_el(centred(np_, nb, W / 2, H - 64), '#6F8DAE'))
    # collar tag: coral disc with a ring hole, ink glyph, wordmark
    cx, cy, R = 640, 300, 170
    ring = diff(circle(cx, cy - R - 26, 34), circle(cx, cy - R - 26, 22))
    disc = diff(circle(cx, cy, R), circle(cx, cy - R + 26, 11))
    els.append(path_el(ring, '#C9C4BA'))
    els.append(path_el(disc, CORAL))
    g2, gh2 = glyph_w(cx, cy - 92, 150)
    els.append(path_el(g2, INK))
    w2, wb2, _ = wordmark(30)
    els.append(path_el(centred(w2, wb2, cx, cy - 92 + gh2 + 52), INK))
    return svg((0, 0, 840, H), ''.join(els))


def extra_pattern():
    """brand pattern for tissue paper / boxes / site backgrounds: upright paw-houses in a staggered grid,
    a quiet «street of puppy homes», tone on tone (no jaunty rotation: calmer, more premium)."""
    W, H = 1200, 600
    clip = rrect(0, 0, W, H, 40, smooth=1.2)
    els = [path_el(clip, PEACH)]
    marks = []
    step_x, step_y, gw = 200, 150, 76          # tile 200 x 300 (two rows): repeats seamlessly
    gh = (GB[3] - GB[1]) * gw / (GB[2] - GB[0])
    for r in range(H // step_y + 1):
        top = r * step_y + (step_y - gh) / 2     # even air above and below every row
        x = step_x / 2 if r % 2 == 0 else 0
        while x <= W + step_x / 2:
            marks.append(glyph_w(x, top, gw)[0])
            x += step_x
    els.append(path_el(inter(union(*marks), clip), CORAL))
    return svg((0, 0, W, H), ''.join(els))


SUN = '#FFD66B'


def els(parts):
    return ''.join(path_el(p, f) for p, f in parts)


def centre_in(parts_vb, box, h):
    """fit a (parts, vb) of height h centred in box (x, y, w, hbox)."""
    parts, vb = parts_vb
    w = vb[2] * h / vb[3]
    x, y, bw, bh = box
    return fit(parts, vb, x + (bw - w) / 2, y + (bh - h) / 2, h)[0]


def extra_phone():
    """lockup-short where it lives: a 390 px phone header at 1:1 (logo 30 px tall), then 2x on white and on ink.
    1256 x 260: shown at 1:1 in the proof sheet."""
    W, H = 1256, 260
    out = []
    # phone: ink body, page-coloured screen, white header pill, burger
    out.append((rrect(0, 0, 430, H + 60, 52, smooth=1.2), INK))
    out.append((rrect(20, 20, 390, H + 40, 34, smooth=1.2), PAGE))
    out.append((rrect(32, 32, 366, 60, 22, smooth=1.2), '#FFFFFF'))
    out += fit(*lockup_short_parts(CORAL_DEEP, INK), 46, 32 + 15, 30)[0]
    out.append((circle(368, 62, 22), PAGE))
    out.append((union(rrect(360, 56, 16, 2.4, 1.2), rrect(360, 65.6, 16, 2.4, 1.2)), INK))
    # page content hints: a white tile with placeholder bars and a pastel photo slot
    out.append((rrect(32, 104, 366, 200, 26, smooth=1.2), '#FFFFFF'))
    out.append((rrect(48, 120, 150, 140, 18, smooth=1.2), SUN))
    out.append((rrect(214, 128, 160, 14, 7), '#E9E7E2'))
    out.append((rrect(214, 152, 120, 14, 7), '#E9E7E2'))
    out.append((rrect(214, 220, 120, 40, 20), CORAL))
    # 2x on white, and inverse on ink
    out.append((rrect(454, 0, 802, 120, 24, smooth=1.2), '#FFFFFF'))
    out += centre_in(lockup_short_parts(CORAL_DEEP, INK), (454, 0, 802, 120), 60)
    out.append((rrect(454, 140, 802, 120, 24, smooth=1.2), INK))
    out += centre_in(lockup_short_parts(CORAL, PAGE), (454, 140, 802, 120), 60)
    body = els(out)
    clip = rrect(0, 0, W, H, 0)
    return svg((0, 0, W, H), ''.join(path_el(inter(p, clip), f) for p, f in out))


def extra_on_coral():
    """the colour rule: on coral and warm pastels the logo is single-colour ink (#141414) only.
    1256 x 260: shown at 1:1 in the proof sheet."""
    out = []
    out.append((rrect(0, 0, 640, 260, 24, smooth=1.2), CORAL))
    out += centre_in(lockup_parts(INK, INK, INK), (0, 0, 640, 260), 96)
    out.append((rrect(664, 0, 280, 260, 24, smooth=1.2), PEACH))
    g, _ = glyph_w(804, 70, 130)
    out.append((g, INK))
    out.append((rrect(968, 0, 288, 260, 24, smooth=1.2), SUN))
    out += centre_in(lockup_short_parts(INK, INK), (968, 0, 288, 260), 44)
    return svg((0, 0, 1256, 260), els(out))


def write(name, s):
    with open(os.path.join(OUT, name), 'w') as f:
        f.write(s)


if __name__ == '__main__':
    s, vb = lockup(CORAL_DEEP, INK, MUTED)
    write('lockup.svg', s)
    print('lockup ratio', round(vb[2] / vb[3], 2))
    print('short ratio', round(lockup_short(CORAL_DEEP, INK)[1][2] / lockup_short(CORAL_DEEP, INK)[1][3], 2))
    write('lockup-inverse.svg', lockup(CORAL, PAGE, MUTED_INV)[0])
    write('lockup-mono.svg', lockup(INK, INK, INK)[0])
    write('lockup-short.svg', lockup_short(CORAL_DEEP, INK)[0])
    write('mark.svg', mark_svg())
    write('mark-mono.svg', mark_mono())
    write('stacked.svg', stacked())
    write('extra-passport.svg', extra_passport())
    write('extra-pattern.svg', extra_pattern())
    write('extra-phone.svg', extra_phone())
    write('extra-on-coral.svg', extra_on_coral())
    print('ok')
