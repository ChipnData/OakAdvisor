"""Turns one shop-phase screenshot into a GameState."""
from __future__ import annotations
import os
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import layout as L
from . import ocr
from .digits import GlyphBank, read_line, read_price, read_int_pair, text_mask

ASSETS = os.path.join(os.path.dirname(__file__), "assets")


@dataclass
class ShopSlot:
    index: int
    empty: bool = True
    price: int | None = None
    sale: bool = False
    packs: list = field(default_factory=list)
    upgrade_glow: bool = False      # game highlights items that combine with one you own
    name: str | None = None
    match: int = 0
    crop: np.ndarray | None = None


@dataclass
class OwnedItem:
    where: str                      # "tower" or "storage"
    index: int
    tier: int = 1                   # 1 = plain border, 2 = gold (1 star), 3 = purple (2 stars)
    name: str | None = None
    match: int = 0
    box: tuple = ()
    crop: np.ndarray | None = None


@dataclass
class GameState:
    in_shop: bool = False
    gold: int | None = None
    income: int | None = None
    level: int | None = None
    xp: int | None = None
    xp_need: int | None = None
    day: int | None = None
    wins: int | None = None
    hearts: int | None = None
    hearts_max: int | None = None
    reroll_cost: int | None = None
    level_cost: int | None = None
    odds: list = field(default_factory=list)
    shop: list = field(default_factory=list)
    tower: list = field(default_factory=list)
    storage: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def owned(self):
        return [o for o in self.tower + self.storage]


def _crop(img, box):
    x0, y0, x1, y1 = box
    return img[y0:y1, x0:x1]


class Reader:
    def __init__(self, library):
        self.lib = library
        self.bank = GlyphBank(os.path.join(ASSETS, "glyphs.json"))
        self.storage_bg = cv2.imread(os.path.join(ASSETS, "storage_bg.png"))
        self.tower_empty = [cv2.imread(os.path.join(ASSETS, f"tower_empty_{i}.png")) for i in range(6)]
        self.leave_sign = cv2.imread(os.path.join(ASSETS, "leave_sign.png"))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def to_frame(img: np.ndarray) -> np.ndarray:
        if img.shape[1] != L.FRAME_W or img.shape[0] != L.FRAME_H:
            img = cv2.resize(img, (L.FRAME_W, L.FRAME_H), interpolation=cv2.INTER_AREA)
        return img

    def _num(self, frame, box):
        s = read_line(_crop(frame, box), self.bank)
        return int(s) if s.isdigit() else None

    def _cost(self, frame, box):
        c = _crop(frame, box)
        s = read_line(c, self.bank, text_mask(c, 150, 255))
        return int(s) if s.isdigit() else None

    def is_shop(self, frame) -> bool:
        x0, y0, x1, y1 = L.LEAVE_BTN
        region = frame[max(0, y0 - 60):y1 + 60, max(0, x0 - 60):x1 + 60]
        r = cv2.matchTemplate(region, self.leave_sign, cv2.TM_CCOEFF_NORMED)
        return float(r.max()) > 0.6

    # ------------------------------------------------------------------ main read
    def read(self, img: np.ndarray, identify: bool = True) -> GameState:
        frame = self.to_frame(img)
        st = GameState()
        st.in_shop = self.is_shop(frame)
        if not st.in_shop:
            st.warnings.append("Shop screen not detected — open the shop, then scan.")
            return st

        st.gold = self._num(frame, L.GOLD)
        st.day = self._num(frame, L.DAY)
        st.wins, _ = read_int_pair(_crop(frame, L.TROPHIES), self.bank)
        st.hearts, st.hearts_max = read_int_pair(_crop(frame, L.HEARTS), self.bank)
        st.xp, st.xp_need = read_int_pair(_crop(frame, L.XP), self.bank)
        st.reroll_cost = self._cost(frame, L.REROLL_COST)
        st.level_cost = self._cost(frame, L.LEVEL_COST)

        # One OCR pass over the shop reads every pack tag; the other text is read with OCR too.
        self._read_text(frame, st)
        self._read_shop(frame, st)
        self._read_tower(frame, st)
        self._read_storage(frame, st)
        if identify:
            self.identify_all(st)
        for k in ("gold", "hearts", "wins", "day"):
            if getattr(st, k) is None:
                st.warnings.append(f"Couldn't read {k} — is a tooltip or menu covering it?")
        return st

    def _read_text(self, frame, st: GameState):
        st._tags = []
        try:
            x0, y0, x1, y1 = L.SHOP_OCR_REGION
            boxes = ocr.read_boxes(frame[y0:y1, x0:x1], offset=(x0, y0))
            for bx0, by0, bx1, by1, text, conf in boxes:
                for w in ocr.split_tag_words(text):
                    p = ocr.as_pack(w)
                    if p:
                        st._tags.append(((bx0 + bx1) / 2, (by0 + by1) / 2, p))
            # HUD text lines (income/level/odds) — cheap, small crops
            for box, attr in ((L.INCOME, "income"), (L.LEVEL, "level")):
                bx = ocr.read_boxes(_crop(frame, box))
                digits = re.findall(r"\d+", " ".join(b[4] for b in bx))
                if digits:
                    setattr(st, attr, int(digits[-1]))
            bx = ocr.read_boxes(_crop(frame, L.ODDS))
            st.odds = [int(v) for v in re.findall(r"(\d+)%", " ".join(b[4] for b in bx))][:4]
        except Exception as e:  # OCR model missing / failed — numbers still work
            st.warnings.append(f"Text reader unavailable ({e}); pack tags not read.")

    def _read_shop(self, frame, st: GameState):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        tags = getattr(st, "_tags", [])
        for i in range(len(L.SHOP_ICON)):
            slot = ShopSlot(index=i)
            slot.price, slot.sale = read_price(_crop(frame, L.SHOP_PRICE[i]), self.bank)
            slot.empty = slot.price is None
            if not slot.empty:
                x0, y0, x1, y1 = L.SHOP_TAG[i]
                slot.packs = sorted({p for (cx, cy, p) in tags if x0 - 10 <= cx <= x1 + 10 and y0 - 14 <= cy <= y1 + 14})
                h = _crop(hsv, L.SHOP_ICON[i])
                purple = (h[..., 0] > 125) & (h[..., 0] < 160) & (h[..., 1] > 80) & (h[..., 2] > 70)
                slot.upgrade_glow = float(purple.mean()) > 0.2
                slot.crop = _crop(frame, L.SHOP_ICON[i]).copy()
            st.shop.append(slot)

    def _read_tower(self, frame, st: GameState):
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        for i in range(6):
            inner = _crop(frame, L.tower_inner(i))
            ref = self.tower_empty[i]
            diff = cv2.absdiff(inner, ref).astype(np.int16).sum(axis=2)
            if (diff > 60).mean() < 0.03:
                continue  # empty tile
            x0, y0, x1, y1 = L.TOWER[i]
            ring = np.concatenate([hsv[y0 + 40:y1 - 40, x0 + 2:x0 + 10].reshape(-1, 3),
                                   hsv[y0 + 40:y1 - 40, x1 - 10:x1 - 2].reshape(-1, 3)])
            hh, ss, _ = np.median(ring, axis=0)
            tier = 1                      # plain grey frame
            if 115 < hh < 170 and ss > 30:
                tier = 3                  # purple frame, two stars
            elif 8 < hh < 35 and ss > 80:
                tier = 2                  # gold frame, one star
            st.tower.append(OwnedItem("tower", i, tier, box=L.TOWER[i], crop=inner.copy()))

    def _read_storage(self, frame, st: GameState):
        x0, y0, x1, y1 = L.STORAGE
        area = frame[y0:y1, x0:x1]
        d = cv2.absdiff(area, self.storage_bg).astype(np.int16).sum(axis=2)
        m = (d > 70).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        m = cv2.dilate(m, np.ones((9, 9), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        k = 0
        for j in range(1, n):
            bx, by, bw, bh, a = stats[j]
            if a < 1500 or bw < 30 or bh < 30:
                continue
            pad = 4
            gx0, gy0 = max(0, bx - pad), max(0, by - pad)
            gx1, gy1 = min(area.shape[1], bx + bw + pad), min(area.shape[0], by + bh + pad)
            crop = area[gy0:gy1, gx0:gx1].copy()
            st.storage.append(OwnedItem("storage", k, 1, box=(x0 + gx0, y0 + gy0, x0 + gx1, y0 + gy1), crop=crop))
            k += 1

    # ------------------------------------------------------------------ recognition
    def identify_all(self, st: GameState):
        lib = self.lib
        for o in st.tower + st.storage:
            o.name, o.match, _ = lib.identify(o.crop, o.where)
        owned_names = {o.name for o in st.owned() if o.name}
        for s in st.shop:
            if s.empty:
                continue
            s.name, s.match, _ = lib.identify(s.crop, "shop")
            if s.name is None and s.upgrade_glow and owned_names:
                # the glow means it's a copy of something we own; check only those, more leniently
                s.name, s.match, _ = lib.identify(s.crop, "shop", only=owned_names, min_inliers=10)
            if s.name:
                it = lib.items.get(s.name)
                if it is not None and s.packs and not set(s.packs) <= set(it.packs):
                    lib.upsert(s.name, packs=s.packs)
                if s.match >= 45:
                    lib.add_template(s.name, "shop", s.crop)  # keeps learning new looks
        for o in st.tower + st.storage:
            if o.name and o.match >= 45:
                lib.add_template(o.name, o.where, o.crop)

    def target_at(self, st: GameState, x: float, y: float):
        """Which shop slot / owned item is under frame point (x, y)."""
        kind, idx = L.which_slot(x, y)
        if kind == "shop":
            s = st.shop[idx] if idx < len(st.shop) else None
            return ("shop", s) if s and not s.empty else (None, None)
        if kind == "tower":
            for o in st.tower:
                if o.index == idx:
                    return "tower", o
            return None, None
        if kind == "storage":
            best = None
            for o in st.storage:
                x0, y0, x1, y1 = o.box
                if x0 <= x <= x1 and y0 <= y <= y1:
                    return "storage", o
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                dist = (cx - x) ** 2 + (cy - y) ** 2
                if best is None or dist < best[0]:
                    best = (dist, o)
            if best and best[0] < 120 ** 2:
                return "storage", best[1]
        return None, None


# ---------------------------------------------------------------------- tooltip
def parse_tooltip(frame: np.ndarray, near=None) -> dict | None:
    """Read the item tooltip that is open on screen (hover an item first).

    Returns {name, rarity, cooldown, damage, effects, type} or None."""
    boxes = ocr.read_boxes(frame, scale=0.6)
    rar = [(b, ocr.as_rarity(b[4])) for b in boxes]
    rar = [(b, r) for b, r in rar if r]
    if not rar:
        return None
    if near is not None and len(rar) > 1:
        rar.sort(key=lambda br: ((br[0][0] + br[0][2]) / 2 - near[0]) ** 2 + ((br[0][1] + br[0][3]) / 2 - near[1]) ** 2)
    rb, rarity = rar[0]
    rcx = (rb[0] + rb[2]) / 2
    above = [b for b in boxes if b[3] <= rb[1] + 4 and rb[1] - b[3] < 90 and abs((b[0] + b[2]) / 2 - rcx) < 200]
    if not above:
        return None
    nb = max(above, key=lambda b: b[3])
    name = re.sub(r"\s+", " ", nb[4]).strip(" .,:;|")
    left, right = rcx - 300, rcx + 300
    below = sorted([b for b in boxes if b[1] > rb[3] and b[1] - rb[3] < 650 and left <= (b[0] + b[2]) / 2 <= right],
                   key=lambda b: (b[1], b[0]))
    cooldown = damage = ""
    effects, words = [], []
    for b in below:
        t = b[4]
        if not cooldown and re.fullmatch(r".{0,3}\d+(\.\d+)?s", t.replace(" ", "")):
            cooldown = re.search(r"\d+(\.\d+)?s", t.replace(" ", "")).group(0)
        elif not damage and re.fullmatch(r"[x×X*+]?\s*\d+", t.strip()):
            damage = re.search(r"\d+", t).group(0)
        elif len(t) > 12 or " " in t.strip():
            effects.append(t)
        else:
            words.append(b)
    item_type = ""
    if words:
        last = max(words, key=lambda b: b[1])
        if last[4].isalpha():
            item_type = last[4]
    return {"name": name, "rarity": rarity, "cooldown": cooldown, "damage": damage,
            "effects": " ".join(effects), "type": item_type}
