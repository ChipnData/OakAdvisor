from __future__ import annotations
import json
import os
import shutil
import sys
from dataclasses import asdict, fields

from .advisor import Settings

APP_NAME = "OakAdvisor"


def data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def assets_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "assets")


DEFAULTS = {
    "hotkeys": {"scan": "F8", "learn": "F9", "overlay": "F10"},
    "window_title": "Oaken Tower",
    "monitor": 1,
    "manual_area": None,
    "overlay_on": True,
    "auto_rescan_after_learn": True,
}


def seed_library(root: str):
    """First run: copy the starter item list that ships with the app."""
    if os.path.exists(os.path.join(root, "items.json")):
        return
    seed = os.path.join(assets_dir(), "seed")
    if os.path.isdir(seed):
        for name in os.listdir(seed):
            src = os.path.join(seed, name)
            dst = os.path.join(root, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)


def load() -> tuple[dict, Settings]:
    path = os.path.join(data_dir(), "settings.json")
    cfg = dict(DEFAULTS)
    adv = Settings()
    if os.path.exists(path):
        try:
            raw = json.load(open(path, encoding="utf-8"))
            cfg.update({k: v for k, v in raw.get("app", {}).items() if k in DEFAULTS})
            names = {f.name for f in fields(Settings)}
            for k, v in raw.get("advisor", {}).items():
                if k in names:
                    setattr(adv, k, v)
        except Exception as e:
            print("settings.json unreadable, using defaults:", e, file=sys.stderr)
    return cfg, adv


def save(cfg: dict, adv: Settings):
    path = os.path.join(data_dir(), "settings.json")
    json.dump({"app": cfg, "advisor": asdict(adv)}, open(path, "w", encoding="utf-8"), indent=1)
