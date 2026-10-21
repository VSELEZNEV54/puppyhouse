"""measure the real gaps between neighbouring shapes along the x-height band"""
import numpy as np
from geo import *
from pathops import Path


def raster_rows(p, ys):
    """for each y: list of (xmin, xmax) of the shape on that scanline (via intersection with thin strips)"""
    out = []
    x0, y0, x1, y1 = p.bounds
    for y in ys:
        s = inter(p, rect(x0 - 1, y - 0.05, x1 + 1, y + 0.05))
        if s.area == 0 if hasattr(s, 'area') else False:
            out.append(None); continue
        try:
            b = s.bounds
        except Exception:
            out.append(None); continue
        out.append(b if b[2] > b[0] else None)
    return out


def gaps(a, b, y0, y1, n=60, depth=None):
    """horizontal gaps between right edge of a and left edge of b for y in [y0, y1]"""
    ys = np.linspace(y0, y1, n)
    ra, rb = raster_rows(a, ys), raster_rows(b, ys)
    g = []
    for A, B in zip(ra, rb):
        if A is None or B is None:
            continue
        g.append(B[0] - A[2])
    g = np.array(g)
    if depth is not None:
        g = np.minimum(g, depth)
    return g.min(), g.mean()
