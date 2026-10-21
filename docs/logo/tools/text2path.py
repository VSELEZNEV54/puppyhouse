#!/usr/bin/env python3
"""Turn text into SVG outlines (no fonts needed in the final logo).

Shaping (kerning, ligatures) by HarfBuzz, outlines straight from the font, variable axes supported.

  python3 text2path.py --font Nunito[wght].ttf --var wght=1000 --size 200 --text "домщенков"
  python3 text2path.py --font Nunito[wght].ttf --var wght=900 --size 120 --tracking -30 --text "дом" --svg out.svg
  python3 text2path.py --list-fonts

Prints JSON:
  d        one path for the whole line, baseline at y=0 (y grows downward, as in SVG), first glyph's origin at x=0
  bbox     [x0, y0, x1, y1] of the ink
  advance  total advance width (where the next glyph would start)
  ascender / descender / xheight / capheight in px for this size
  glyphs   per glyph: char, x (origin), advance, d, bbox  - use it to place a paw in a counter, recolour a letter, etc.
Options: --x/--y move the origin, --tracking adds px between glyphs, --features "ss01,-liga".
--font may be a bare file name from ../fonts or a path.
"""
import argparse, json, os, sys
import uharfbuzz as hb

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.normpath(os.path.join(HERE, '..', 'fonts'))


class PathPen:
    """Collects hb draw callbacks into an SVG path (font units, y up) with a transform applied."""
    def __init__(self, sx, ox, oy):
        self.sx, self.ox, self.oy = sx, ox, oy
        self.parts = []
        self.xs, self.ys = [], []

    def _p(self, x, y):
        X = self.ox + x * self.sx
        Y = self.oy - y * self.sx
        self.xs.append(X); self.ys.append(Y)
        return f"{X:.2f} {Y:.2f}"

    def moveTo(self, p): self.parts.append("M" + self._p(*p))
    def lineTo(self, p): self.parts.append("L" + self._p(*p))
    def qCurveTo(self, *pts):
        # hb gives exactly one control point + end point
        c, e = pts
        self.parts.append("Q" + self._p(*c) + " " + self._p(*e))
    def curveTo(self, c1, c2, e):
        self.parts.append("C" + self._p(*c1) + " " + self._p(*c2) + " " + self._p(*e))
    def closePath(self): self.parts.append("Z")
    def endPath(self): pass

    def d(self): return "".join(self.parts)
    def bbox(self):
        if not self.xs: return None
        return [round(min(self.xs), 2), round(min(self.ys), 2), round(max(self.xs), 2), round(max(self.ys), 2)]


def resolve(font):
    if os.path.exists(font): return font
    p = os.path.join(FONTS, font)
    if os.path.exists(p): return p
    sys.exit(f"font not found: {font} (see --list-fonts)")


def shape(font_path, text, size, var=None, tracking=0.0, features=None, x=0.0, y=0.0):
    blob = hb.Blob.from_file_path(font_path)
    face = hb.Face(blob)
    font = hb.Font(face)
    if var: font.set_variations(var)
    upem = face.upem
    s = size / upem
    buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
    feats = {}
    for f in (features or []):
        f = f.strip()
        if not f: continue
        feats[f.lstrip('-+')] = not f.startswith('-')
    hb.shape(font, buf, feats)
    ext = font.get_font_extents('ltr')
    glyphs, all_parts, xs, ys = [], [], [], []
    pen_x = x
    clusters = [i.cluster for i in buf.glyph_infos]
    for idx, (info, pos) in enumerate(zip(buf.glyph_infos, buf.glyph_positions)):
        gx = pen_x + pos.x_offset * s
        gy = y - pos.y_offset * s
        pen = PathPen(s, gx, gy)
        font.draw_glyph_with_pen(info.codepoint, pen)
        start = info.cluster
        nxt = [c for c in clusters if c > start]
        end = min(nxt) if nxt else len(text)
        adv = pos.x_advance * s + tracking
        glyphs.append(dict(char=text[start:end], gid=info.codepoint, x=round(gx, 2), advance=round(adv, 2),
                           d=pen.d(), bbox=pen.bbox()))
        all_parts.append(pen.d()); xs += pen.xs; ys += pen.ys
        pen_x += adv
    out = dict(
        font=os.path.basename(font_path), size=size, var=var or {}, text=text,
        d="".join(all_parts),
        bbox=[round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)] if xs else None,
        advance=round(pen_x - x - tracking, 2),
        ascender=round(ext.ascender * s, 2), descender=round(ext.descender * s, 2),
        glyphs=glyphs,
    )
    try:
        from fontTools.ttLib import TTFont
        os2 = TTFont(font_path, lazy=True)['OS/2']
        out['xheight'] = round(getattr(os2, 'sxHeight', 0) * s, 2)
        out['capheight'] = round(getattr(os2, 'sCapHeight', 0) * s, 2)
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--font'); ap.add_argument('--text'); ap.add_argument('--size', type=float, default=100)
    ap.add_argument('--var', action='append', default=[], help='axis=value, e.g. wght=900 (repeatable)')
    ap.add_argument('--tracking', type=float, default=0.0)
    ap.add_argument('--features', default='')
    ap.add_argument('--x', type=float, default=0.0); ap.add_argument('--y', type=float, default=0.0)
    ap.add_argument('--svg', help='also write a preview SVG here')
    ap.add_argument('--no-glyphs', action='store_true', help='omit per-glyph data from the JSON')
    ap.add_argument('--list-fonts', action='store_true')
    a = ap.parse_args()
    if a.list_fonts:
        from fontTools.ttLib import TTFont
        for f in sorted(os.listdir(FONTS)):
            if not f.endswith('.ttf'): continue
            t = TTFont(os.path.join(FONTS, f), lazy=True)
            axes = [f"{x.axisTag} {x.minValue:g}-{x.maxValue:g}" for x in t['fvar'].axes] if 'fvar' in t else []
            print(f, ', '.join(axes))
        return
    if not a.font or a.text is None: ap.error('--font and --text are required')
    var = {}
    for v in a.var:
        k, val = v.split('='); var[k] = float(val)
    res = shape(resolve(a.font), a.text, a.size, var, a.tracking,
                [f for f in a.features.split(',') if f], a.x, a.y)
    if a.svg and res['bbox']:
        x0, y0, x1, y1 = res['bbox']; pad = a.size * 0.1
        with open(a.svg, 'w') as fh:
            fh.write(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0-pad:.1f} {y0-pad:.1f} {x1-x0+2*pad:.1f} {y1-y0+2*pad:.1f}">'
                     f'<path d="{res["d"]}" fill="#141414"/></svg>\n')
    if a.no_glyphs: res.pop('glyphs')
    json.dump(res, sys.stdout, ensure_ascii=False)
    print()


if __name__ == '__main__':
    main()
