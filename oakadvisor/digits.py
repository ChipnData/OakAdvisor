"""Reads the game's outlined white numbers without a heavy OCR model.

Text pixels are bright + unsaturated; each glyph is a connected blob that we
normalise and compare to a small bank of glyph templates (built from real
screenshots, see tools/build_glyphs.py)."""
from __future__ import annotations
import json, os
import cv2
import numpy as np

GW, GH = 20, 28  # normalised glyph size


def text_mask(crop: np.ndarray, vmin: int = 165, smax: int = 95) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 2] > vmin) & (hsv[:, :, 1] < smax)).astype(np.uint8)


def red_mask(crop: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h < 8) | (h > 170)) & (s > 120) & (v > 120)).astype(np.uint8)


def components(mask: np.ndarray, min_h_frac: float = 0.35):
    """Return glyph boxes (x,y,w,h) sorted left->right, merging blobs stacked in x."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = [tuple(st[i, :4]) for i in range(1, n) if st[i, 4] >= 6]
    if not boxes:
        return []
    hmax = max(b[3] for b in boxes)
    boxes = [b for b in boxes if b[3] >= hmax * min_h_frac]
    boxes.sort(key=lambda b: b[0])
    merged = []
    for b in boxes:  # merge boxes whose x-ranges mostly overlap (e.g. % pieces)
        if merged:
            m = merged[-1]
            ov = min(m[0] + m[2], b[0] + b[2]) - max(m[0], b[0])
            if ov > 0.6 * min(m[2], b[2]):
                x0, y0 = min(m[0], b[0]), min(m[1], b[1])
                x1, y1 = max(m[0] + m[2], b[0] + b[2]), max(m[1] + m[3], b[1] + b[3])
                merged[-1] = (x0, y0, x1 - x0, y1 - y0)
                continue
        merged.append(b)
    return merged


def norm_glyph(mask: np.ndarray, box, ref_h: int) -> np.ndarray:
    x, y, w, h = box
    g = mask[y:y + h, x:x + w].astype(np.float32)
    # keep aspect: place into a canvas sized by the line height
    canvas_h = max(ref_h, h)
    canvas_w = max(int(canvas_h * GW / GH), w)
    c = np.zeros((canvas_h, canvas_w), np.float32)
    oy = canvas_h - h  # bottom aligned (digits sit on baseline)
    ox = (canvas_w - w) // 2
    c[oy:oy + h, ox:ox + w] = g
    return cv2.resize(c, (GW, GH), interpolation=cv2.INTER_AREA)


class GlyphBank:
    def __init__(self, path: str | None = None):
        self.items: list[tuple[str, np.ndarray]] = []
        if path and os.path.exists(path):
            data = json.load(open(path))
            for ch, arr in data:
                self.items.append((ch, np.array(arr, np.float32).reshape(GH, GW)))

    def add(self, ch: str, g: np.ndarray):
        self.items.append((ch, g))

    def save(self, path: str):
        json.dump([(c, np.round(g, 3).flatten().tolist()) for c, g in self.items], open(path, "w"))

    def classify(self, g: np.ndarray) -> tuple[str, float]:
        best, bs = "?", -1.0
        a = g - g.mean()
        na = np.linalg.norm(a) + 1e-6
        for ch, t in self.items:
            b = t - t.mean()
            s = float((a * b).sum() / (na * (np.linalg.norm(b) + 1e-6)))
            if s > bs:
                best, bs = ch, s
        return best, bs


def read_line(crop: np.ndarray, bank: GlyphBank, mask: np.ndarray | None = None,
              min_score: float = 0.55) -> str:
    m = text_mask(crop) if mask is None else mask
    boxes = components(m)
    if not boxes:
        return ""
    ref_h = max(b[3] for b in boxes)
    out = []
    for b in boxes:
        ch, s = bank.classify(norm_glyph(m, b, ref_h))
        if s >= min_score:
            out.append(ch)
    return "".join(out)


def lines(mask: np.ndarray):
    """Split a mask into horizontal text bands (top->bottom)."""
    rows = mask.sum(axis=1) > 0
    bands, start = [], None
    for i, r in enumerate(rows):
        if r and start is None:
            start = i
        elif not r and start is not None:
            if i - start >= 6:
                bands.append((start, i))
            start = None
    if start is not None and len(rows) - start >= 6:
        bands.append((start, len(rows)))
    return bands


def sale_star_right_edge(crop: np.ndarray) -> int | None:
    """x of the right edge of the red 'SALE' starburst, or None if there is no sale."""
    r = red_mask(crop)
    n, lab, st, _ = cv2.connectedComponentsWithStats(r, connectivity=8)
    if n <= 1:
        return None
    i = 1 + int(np.argmax(st[1:, 4]))
    if st[i, 4] < 400:
        return None
    return int(st[i, 0] + st[i, 2])


def read_price(crop: np.ndarray, bank: GlyphBank) -> tuple[int | None, bool]:
    edge = sale_star_right_edge(crop)
    sale = edge is not None
    for smax in (95, 170):
        m = text_mask(crop, 165, smax)
        if sale:
            m[:, :edge + 2] = 0
        bands = [bd for bd in lines(m) if bd[1] - bd[0] >= 18]
        if not bands:
            continue
        a, b = bands[-1] if sale else max(bands, key=lambda bd: bd[1] - bd[0])
        sub = np.zeros_like(m)
        sub[a:b] = m[a:b]
        s = read_line(crop, bank, sub)
        if s.isdigit() and len(s) <= 3:
            return int(s), sale
    return None, sale


def read_int_pair(crop: np.ndarray, bank: GlyphBank, **kw) -> tuple[int | None, int | None]:
    s = read_line(crop, bank, **kw)
    if "/" in s:
        a, _, b = s.partition("/")
        return (int(a) if a.isdigit() else None, int(b) if b.isdigit() else None)
    return (int(s) if s.isdigit() else None, None)
