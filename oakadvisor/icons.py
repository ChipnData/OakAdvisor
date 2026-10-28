"""Item library: what each item is (name, packs, rarity, your rating) plus the
icon pictures used to recognise it on screen.

Recognition uses SIFT keypoints, which ignore the different backgrounds behind
an item in the shop, in a tower tile and in storage. A cheap colour-histogram
pass picks the most likely candidates first so a scan stays fast."""
from __future__ import annotations
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict

import cv2
import numpy as np

MIN_INLIERS = 22       # keypoints that must agree for a confident match
MARGIN = 1.6           # best match must beat the runner-up (a different item) by this factor
MAX_TEMPLATES_PER_CONTEXT = 4


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "item"


@dataclass
class Item:
    name: str
    packs: list = field(default_factory=list)
    rarity: str = ""
    type: str = ""
    cooldown: str = ""
    damage: str = ""
    effects: str = ""
    rating: str = ""        # S / A / B / C / D / "" (unrated) — set by you in the Library
    notes: str = ""
    consumable: bool = False


@dataclass
class Template:
    item: str
    context: str
    path: str
    kp: list
    des: np.ndarray | None
    hist: np.ndarray


def _prep(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST), cv2.COLOR_BGR2GRAY)


def _hist(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 60) | (hsv[:, :, 2] > 190)).astype(np.uint8)  # ignore dull backgrounds
    h = cv2.calcHist([hsv], [0, 1], mask, [18, 6], [0, 180, 0, 256])
    cv2.normalize(h, h)
    return h


class IconLibrary:
    def __init__(self, root: str):
        self.root = root
        self.icon_dir = os.path.join(root, "icons")
        self.unknown_dir = os.path.join(root, "unknown")
        os.makedirs(self.icon_dir, exist_ok=True)
        os.makedirs(self.unknown_dir, exist_ok=True)
        self.db_path = os.path.join(root, "items.json")
        self.items: dict[str, Item] = {}
        self.templates: list[Template] = []
        self._sift = cv2.SIFT_create()
        self._bf = cv2.BFMatcher()
        self.load()

    # ---------- persistence ----------
    def load(self):
        self.items.clear()
        if os.path.exists(self.db_path):
            data = json.load(open(self.db_path, encoding="utf-8"))
            for d in data.get("items", []):
                known = {k: v for k, v in d.items() if k in Item.__dataclass_fields__}
                it = Item(**known)
                self.items[it.name] = it
        self.templates.clear()
        for name in self.items:
            folder = os.path.join(self.icon_dir, slug(name))
            if not os.path.isdir(folder):
                continue
            for fn in sorted(os.listdir(folder)):
                if fn.endswith(".png"):
                    img = cv2.imread(os.path.join(folder, fn))
                    if img is not None:
                        self._add_template_obj(name, fn.split("_")[0], os.path.join(folder, fn), img)

    def save(self):
        data = {"items": [asdict(i) for i in sorted(self.items.values(), key=lambda i: i.name)]}
        tmp = self.db_path + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, self.db_path)

    # ---------- editing ----------
    def upsert(self, name: str, **fields) -> Item:
        it = self.items.get(name) or Item(name=name)
        for k, v in fields.items():
            if v in (None, "", []):
                continue
            if k == "packs":
                v = sorted(set(it.packs) | set(v))
            setattr(it, k, v)
        self.items[name] = it
        return it

    def rename(self, old: str, new: str):
        if old == new or old not in self.items:
            return
        it = self.items.pop(old)
        it.name = new
        if new in self.items:  # merge into existing item
            tgt = self.items[new]
            tgt.packs = sorted(set(tgt.packs) | set(it.packs))
        else:
            self.items[new] = it
        src, dst = os.path.join(self.icon_dir, slug(old)), os.path.join(self.icon_dir, slug(new))
        if os.path.isdir(src):
            os.makedirs(dst, exist_ok=True)
            for fn in os.listdir(src):
                os.replace(os.path.join(src, fn), os.path.join(dst, f"{fn[:-4]}_{int(time.time()*1000)%100000}.png"))
            os.rmdir(src)
        self.save()
        self.load()

    def delete(self, name: str):
        self.items.pop(name, None)
        folder = os.path.join(self.icon_dir, slug(name))
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                os.remove(os.path.join(folder, fn))
            os.rmdir(folder)
        self.save()
        self.load()

    def add_template(self, name: str, context: str, img: np.ndarray) -> bool:
        """Store another picture of an item. Returns False if that context already has enough."""
        have = [t for t in self.templates if t.item == name and t.context == context]
        if len(have) >= MAX_TEMPLATES_PER_CONTEXT:
            return False
        folder = os.path.join(self.icon_dir, slug(name))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{context}_{int(time.time() * 1000)}.png")
        cv2.imwrite(path, img)
        self._add_template_obj(name, context, path, img)
        return True

    def _add_template_obj(self, name, context, path, img):
        kp, des = self._sift.detectAndCompute(_prep(img), None)
        self.templates.append(Template(name, context, path, kp or [], des, _hist(img)))

    def save_unknown(self, img: np.ndarray, context: str) -> str:
        path = os.path.join(self.unknown_dir, f"{context}_{int(time.time() * 1000)}.png")
        cv2.imwrite(path, img)
        return path

    # ---------- recognition ----------
    def _inliers(self, kp, des, t: Template) -> int:
        if des is None or t.des is None or len(des) < 2 or len(t.des) < 2:
            return 0
        pairs = self._bf.knnMatch(des, t.des, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 4:
            return len(good)
        pa = np.float32([kp[m.queryIdx].pt for m in good])
        pb = np.float32([t.kp[m.trainIdx].pt for m in good])
        _, inl = cv2.estimateAffinePartial2D(pa, pb, ransacReprojThreshold=8)
        return int(inl.sum()) if inl is not None else 0

    def identify(self, img: np.ndarray, context: str = "", only: set | None = None,
                 shortlist: int = 30, min_inliers: int = MIN_INLIERS):
        """Return (name or None, best_inliers, runner_up_inliers)."""
        if not self.templates or img is None or img.size == 0:
            return None, 0, 0
        kp, des = self._sift.detectAndCompute(_prep(img), None)
        if des is None:
            return None, 0, 0
        h = _hist(img)
        cands = [t for t in self.templates if (only is None or t.item in only)]
        cands.sort(key=lambda t: -cv2.compareHist(h, t.hist, cv2.HISTCMP_CORREL))
        cands = cands[:shortlist]
        # same-context templates are the most reliable; always include them
        best: dict[str, int] = {}
        for t in cands:
            s = self._inliers(kp, des, t)
            if context and t.context == context:
                s = int(s * 1.1)
            best[t.item] = max(best.get(t.item, 0), s)
        if not best:
            return None, 0, 0
        ranked = sorted(best.items(), key=lambda kv: -kv[1])
        name, s1 = ranked[0]
        s2 = ranked[1][1] if len(ranked) > 1 else 0
        if s1 >= min_inliers and s1 >= MARGIN * max(s2, 1):
            return name, s1, s2
        return None, s1, s2
