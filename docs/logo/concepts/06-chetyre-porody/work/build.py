#!/usr/bin/env python3
"""06-chetyre-porody «Четыре породы» v2 — single source of truth for every deliverable.
Run: python3 build.py            (writes ../*.svg)
     python3 build.py <outdir>   (writes into another folder, for studies)
"""
import hashlib, json, math, os, re, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import *            # noqa
from paw2 import build_paw   # noqa

OUT = os.path.dirname(HERE)

# ---------------- palette ----------------
INK = '#141414'
CREAM = '#F3F2EF'      # site page colour = the warm light of home
MUTED = '#6B6B6B'
MUTED_INV = '#A3A19C'
DIM = '#3D3B38'        # unlit toe on ink (breed variants)
# breed tones = the site's own studio backdrops per breed (assets/css/main.css: --peach/--powder/--butter/--sage)
PEACH = '#F1BC94'    # мальтипу
POWDER = '#A7D0E6'   # французский бульдог
BUTTER = '#E9CB8A'   # той-пудель
SAGE = '#A9C8B1'     # бордер-колли
TONES = [PEACH, POWDER, BUTTER, SAGE]
BREEDS = ['мальтипу', 'французский бульдог', 'той-пудель', 'бордер-колли']

# ---------------- config (studies override this) ----------------
CFG = dict(
    font='MPLUSRounded1c-Medium.ttf', wvar={}, track=-0.02,
    # optical kerning (em), measured on the outlines: д|о, щ|е, к|о were loose, р|ф too tight, the dot sat wide
    kern={0: -0.022, 3: -0.018, 6: -0.03, 8: -0.01, 9: -0.012, 10: 0.01},
    dil=0.008,           # Medium thickened by a round offset of 0.8 % em: between Medium and Bold, terminals stay round
    inv_dil=0.004,       # light-on-dark looks heavier: the inverse gets half the offset
    tfont='MPLUSRounded1c-Medium.ttf', tvar={}, ttrack=0.03,
    inv_dw=0,
    ws_k=0.62, ts_k=0.255, gap_k=0.24, lead_k=0.075,
    paw=dict(pw=60, ph=46, top=0.42, corner=0.26, smooth=13.0, out_n=120, r=12.3, sq=1.12, k_out=0.87, gap=3.8, gap_tt=3.8, ody=11),
    fill=0.78,           # paw width / tile
    dy=-0.008,           # optical nudge of the paw in the tile (fraction of tile, - = up)
    tile_n=4.2,
)

_PAW = {}


def paw_unit():
    """pad + 4 toes, normalised to width 100, centred on (0,0). Cached on disk (the gap solver is slow)."""
    key = json.dumps(CFG['paw'], sort_keys=True)
    if key in _PAW:
        return _PAW[key]
    cache = os.path.join(HERE, 'paw_cache.json')
    db = json.load(open(cache)) if os.path.exists(cache) else {}
    h = hashlib.md5(key.encode()).hexdigest()
    if h not in db:
        pad, toes, _ = build_paw(**CFG['paw'])
        b = union(pad, *toes).bounds
        s = 100 / (b[2] - b[0]); cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        tf = lambda p: p.transform(s, 0, 0, s, -cx * s, -cy * s)
        db[h] = dict(pad=to_d(tf(pad)), toes=[to_d(tf(t)) for t in toes], h=(b[3] - b[1]) * s)
        json.dump(db, open(cache, 'w'))
    e = db[h]
    r = (d_to_path(e['pad']), [d_to_path(t) for t in e['toes']], e['h'])
    _PAW[key] = r
    return r


def paw_at(cx, cy, w):
    pad, toes, _ = paw_unit()
    s = w / 100
    f = lambda p: p.transform(s, 0, 0, s, cx, cy)
    return f(pad), [f(t) for t in toes]


def paw_svg(cx, cy, w, padcol, toecols):
    pad, toes = paw_at(cx, cy, w)
    if isinstance(toecols, str):
        toecols = [toecols] * 4
    return pathel(pad, padcol) + ''.join(pathel(t, c) for t, c in zip(toes, toecols))


def tile(x, y, s):
    return superellipse(x + s / 2, y + s / 2, s / 2, s / 2, CFG['tile_n'], steps=64)


def mark_svg(x, y, s, toecols=TONES, padcol=CREAM, tilecol=INK):
    cx, cy = x + s / 2, y + s / 2 + CFG['dy'] * s
    return pathel(tile(x, y, s), tilecol) + paw_svg(cx, cy, s * CFG['fill'], padcol, toecols)


def mark_knockout(x, y, s, col=INK):
    cx, cy = x + s / 2, y + s / 2 + CFG['dy'] * s
    pad, toes = paw_at(cx, cy, s * CFG['fill'])
    return pathel(diff(tile(x, y, s), pad, *toes), col)


# ---------------- wordmark ----------------
def _xh(t):
    """x-height measured on a flat-topped lowercase letter of the actual line (н п и м т)."""
    for c in 'нпимт':
        for g in t['glyphs']:
            if g['char'] == c and g['bbox']:
                return -g['bbox'][1]
    return t['xheight']


def wordmark(size, dw=0, inv=False):
    """dil: the static font is thickened by an even round offset (em units), the tracking opens by the same amount."""
    v = dict(CFG['wvar'])
    if dw and 'wght' in v:
        v['wght'] += dw
    dil = CFG['dil'] if not inv or CFG['inv_dil'] is None else CFG['inv_dil']
    kern = {i: k * size for i, k in CFG['kern'].items()}
    t = text(CFG['font'], 'домщенков.рф', size, v, tracking=(CFG['track'] + 2 * dil) * size, kern=kern)
    t['xh'] = _xh(t)
    if dil:
        r = dil * size
        t['path'] = dilate(t['path'], r)
        t['xh'] += r
        b = t['path'].bounds
        t['bbox'] = [b[0], b[1], b[2], b[3]]
    return t


def tagline(size, s='питомник щенков'):
    t = text(CFG['tfont'], s, size, CFG['tvar'], tracking=CFG['ttrack'] * size)
    t['xh'] = _xh(t)
    return t


def block(x, top, H, col_word, col_tag, dw=0, tag='питомник щенков', inv=False):
    """wordmark + tagline; the two x-height bands are centred optically on the tile."""
    ws = H * CFG['ws_k']
    w = wordmark(ws, dw, inv)
    out = ''
    if tag:
        ts = H * CFG['ts_k']
        t = tagline(ts, tag)
        desc = w['bbox'][3]
        lead = desc + H * CFG['lead_k']
        total = w['xh'] + lead + t['xh']
        y0 = top + (H - total) / 2
        base_w = y0 + w['xh']
        base_t = base_w + lead + t['xh']
        # optical left edge: the tagline's «п» stem sits under the «д» bowl stem
        tx = x - t['bbox'][0] + ws * 0.018
        out += pathel(move(t['path'], tx, base_t), col_tag)
        width = max(w['bbox'][2] - w['bbox'][0], t['bbox'][2] - t['bbox'][0] + ws * 0.018)
    else:
        base_w = top + H / 2 + w['xh'] / 2
        width = w['bbox'][2] - w['bbox'][0]
    out = pathel(move(w['path'], x - w['bbox'][0], base_w), col_word) + out
    return out, width


def write(out, name, view, body):
    with open(os.path.join(out, name), 'w') as f:
        f.write(svg(view, body))


def tight(body, pad):
    """viewBox = true ink bounds of every path + even padding."""
    b = None
    for d in re.findall(r' d="([^"]+)"', body):
        bb = d_to_path(d).bounds
        b = bb if b is None else (min(b[0], bb[0]), min(b[1], bb[1]), max(b[2], bb[2]), max(b[3], bb[3]))
    return (b[0] - pad, b[1] - pad, b[2] - b[0] + 2 * pad, b[3] - b[1] + 2 * pad)


def label(s, x, y, size, col, font=None, var=None, anchor='start', track=0.01):
    t = text(font or CFG['tfont'], s, size, var or CFG['tvar'], tracking=track * size)
    w = t['bbox'][2] - t['bbox'][0]
    dx = {'start': 0, 'middle': -w / 2, 'end': -w}[anchor] - t['bbox'][0]
    return pathel(move(t['path'], x + dx, y), col)


def word_at(size, x, y, col, anchor='start', dw=0):
    w = wordmark(size, dw)
    ww = w['bbox'][2] - w['bbox'][0]
    dx = {'start': 0, 'middle': -ww / 2, 'end': -ww}[anchor] - w['bbox'][0]
    return pathel(move(w['path'], x + dx, y), col), ww


# ---------------- deliverables ----------------
def lockup_light(H=100, toecols=TONES, tag='питомник щенков', word=INK, tagcol=MUTED):
    gx = H * CFG['gap_k']
    txt, tw = block(H + gx, 0, H, word, tagcol, tag=tag)
    return mark_svg(0, 0, H, toecols) + txt


def lockup_inverse(H=100, tag='питомник щенков'):
    _, _, ph = paw_unit()
    pw = H * 100 / ph * 0.90          # bare paw shorter than the tile: without a frame it reads bigger
    body = paw_svg(pw / 2, H / 2 - H * 0.01, pw, CREAM, TONES)
    txt, tw = block(pw + H * CFG['gap_k'] * 0.9, 0, H, CREAM, MUTED_INV, dw=CFG['inv_dw'], tag=tag, inv=True)
    return body + txt


def build(out=OUT):
    H = 100
    pad = 6
    b = lockup_light(H)
    write(out, 'lockup.svg', tight(b, pad), b)
    b = lockup_light(H, tag=None)
    write(out, 'lockup-short.svg', tight(b, pad), b)
    b = lockup_inverse(H)
    write(out, 'lockup-inverse.svg', tight(b, pad), b)
    gx = H * CFG['gap_k']
    txt, tw = block(H + gx, 0, H, INK, INK)
    b = mark_knockout(0, 0, H) + txt
    write(out, 'lockup-mono.svg', tight(b, pad), b)
    write(out, 'mark.svg', (0, 0, 100, 100), mark_svg(0, 0, 100))
    write(out, 'mark-mono.svg', (0, 0, 100, 100), mark_knockout(0, 0, 100))
    build_stacked(out)
    build_breeds(out)
    build_passport(out)


def build_stacked(out):
    # square sticker / social card: cream squircle, mark, wordmark, tagline
    C = 400
    body = pathel(superellipse(C / 2, C / 2, C / 2, C / 2, 4.6, steps=72), CREAM)
    w = wordmark(100)
    k = (C * 0.74) / (w['bbox'][2] - w['bbox'][0])   # wordmark spans 74 % of the card
    ws = 100 * k
    w = wordmark(ws)
    S = C * 0.44                                       # tile 44 % of the card
    t = tagline(ws * 0.44)
    ww = w['bbox'][2] - w['bbox'][0]; tw = t['bbox'][2] - t['bbox'][0]
    gap1 = ws * 0.72
    lead = w['bbox'][3] + ws * 0.16
    total = S + gap1 + w['xh'] + lead + t['xh']
    y0 = (C - total) / 2
    body += mark_svg(C / 2 - S / 2, y0, S)
    base_w = y0 + S + gap1 + w['xh']
    body += pathel(move(w['path'], C / 2 - ww / 2 - w['bbox'][0], base_w), INK)
    base_t = base_w + lead + t['xh']
    body += pathel(move(t['path'], C / 2 - tw / 2 - t['bbox'][0], base_t), MUTED)
    write(out, 'stacked.svg', (0, 0, C, C), body)


def build_breeds(out):
    """the system in use: on each breed page the header logo lights only that breed's toe and the tagline
    names the breed; the home page shows all four toes = the whole kennel."""
    H = 100
    body = ''
    for i in range(4):
        cols = [DIM] * 4; cols[i] = TONES[i]
        body += move_svg(lockup_light(H, cols, tag=BREEDS[i]), (i % 2) * 700, (i // 2) * 150)
    write(out, 'extra-breeds.svg', tight(body, 10), body)


def move_svg(body, dx, dy):
    def f(m):
        return ' d="' + to_d(move(d_to_path(m.group(1)), dx, dy)) + '"'
    return re.sub(r' d="([^"]+)"', f, body)


def build_passport(out):
    """puppy passport covers in the four breed tones; on each, the tile with that breed's own toe lit
    (the lit toe is the same colour as the cover: the puppy's breed is "the one that glows")."""
    Wc, Hc = 220, 310
    G = 28
    body = ''
    for i in range(4):
        x = i * (Wc + G)
        body += pathel(rrect(x, 0, Wc, Hc, 16), TONES[i])
        cols = [DIM] * 4
        cols[i] = TONES[i]
        S = 124
        body += mark_svg(x + Wc / 2 - S / 2, 72, S, cols)
        body += label('паспорт щенка', x + Wc / 2, 240, 22, INK, anchor='middle', track=0.005)
        body += label(BREEDS[i], x + Wc / 2, 266, 15, INK, anchor='middle', track=0.02)
        wpath, _ = word_at(16, x + Wc / 2, 40, INK, anchor='middle')
        body += wpath
    W = 4 * Wc + 3 * G
    write(out, 'extra-passport.svg', (-8, -8, W + 16, Hc + 16), body)


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    os.makedirs(out, exist_ok=True)
    build(out)
    print('ok', out)
