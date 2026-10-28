"""Local text recognition (RapidOCR / ONNX, runs fully offline on the CPU)."""
from __future__ import annotations
import difflib
import threading
import numpy as np

from .layout import PACKS, RARITIES

_engine = None
_lock = threading.Lock()


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
    return _engine


def read_boxes(img: np.ndarray, offset=(0, 0), scale: float = 1.0):
    """Return [(x0, y0, x1, y1, text, conf)] in the coordinates of the original image + offset."""
    import cv2
    src = img if scale == 1.0 else cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    res, _ = engine()(src)
    out = []
    for box, text, conf in res or []:
        xs = [p[0] / scale for p in box]
        ys = [p[1] / scale for p in box]
        out.append((int(min(xs)) + offset[0], int(min(ys)) + offset[1],
                    int(max(xs)) + offset[0], int(max(ys)) + offset[1], text.strip(), float(conf)))
    return out


def _clean(s: str) -> str:
    return "".join(ch for ch in s if ch.isalpha())


def match_vocab(word: str, vocab, cutoff: float = 0.6):
    w = _clean(word).lower()
    if not w:
        return None
    best = difflib.get_close_matches(w, [v.lower() for v in vocab], n=1, cutoff=cutoff)
    if not best:
        return None
    return next(v for v in vocab if v.lower() == best[0])


def split_tag_words(text: str):
    """OCR sometimes glues neighbouring tags ('WitchArcane'); split on capitals too."""
    import re
    parts = []
    for chunk in re.split(r"[^A-Za-z]+", text):
        parts += re.findall(r"[A-Z][a-z]+|[a-z]+", chunk)
    return parts


def as_pack(word: str, known=None):
    vocab = list(dict.fromkeys(PACKS + list(known or [])))
    return match_vocab(word, vocab, 0.6)


def as_rarity(word: str):
    w = _clean(word)
    if not w or len(w) > 11:
        return None
    return match_vocab(w, RARITIES, 0.75)
